import asyncio
import aiohttp
import time
import random
import ssl
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup as bs
from pathlib import Path
from openpyxl import Workbook
from fake_useragent import UserAgent
import os
import re
import itertools
from urllib.parse import urlencode

# 기존 클래스들 import (그대로 유지)
from main3 import (
    NonWindowsUserAgent, SaveData, URLManager,
    load_proxy_list_from_file, create_sample_proxy_file,
    is_valid_proxy_format, test_proxy
)


@dataclass
class ProxyStats:
    """프록시 통계 정보"""
    success_count: int = 0
    failure_count: int = 0
    last_used: float = 0
    avg_response_time: float = 0
    total_response_time: float = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5

    @property
    def performance_score(self) -> float:
        """성능 점수 (높을수록 좋음)"""
        if self.avg_response_time == 0:
            return self.success_rate

        # 성공률과 응답시간을 조합한 점수
        time_score = min(1.0, 3.0 / max(self.avg_response_time, 0.1))
        return (self.success_rate * 0.7) + (time_score * 0.3)


class AsyncProxyManager:
    """비동기 프록시 관리자 (프록시당 1개 연결)"""

    def __init__(self, proxy_list: List[str], max_concurrent_per_proxy: int = 1):
        self.proxy_list = proxy_list or []
        self.max_concurrent_per_proxy = max_concurrent_per_proxy  # 1개로 제한
        self.proxy_stats = {proxy: ProxyStats() for proxy in self.proxy_list}
        self.failed_proxies = set()
        self.lock = asyncio.Lock()
        # 세마포어 대신 간단한 연결 카운터 사용
        self.active_connections = defaultdict(int)

    async def get_best_proxy(self) -> Optional[str]:
        """성능 기반 최적 프록시 선택 (보수적 기준)"""
        async with self.lock:
            available_proxies = [
                p for p in self.proxy_list
                if p not in self.failed_proxies and
                   self.active_connections[p] < self.max_concurrent_per_proxy
            ]

            if not available_proxies:
                # 70% 이상의 프록시가 실패했다면 실패 목록 초기화 (기존 80%에서 감소)
                if len(self.failed_proxies) > len(self.proxy_list) * 0.7:
                    print("[WARNING] 70% 이상의 프록시가 실패했습니다. 실패 목록을 초기화합니다.")
                    self.failed_proxies.clear()
                    available_proxies = [
                        p for p in self.proxy_list
                        if self.active_connections[p] < self.max_concurrent_per_proxy
                    ]

            if not available_proxies:
                return None

            # 성능 점수 기반 가중치 선택
            weights = [self.proxy_stats[proxy].performance_score for proxy in available_proxies]
            total_weight = sum(weights)

            if total_weight == 0:
                return random.choice(available_proxies)

            # 가중치 기반 랜덤 선택
            r = random.random() * total_weight
            cumulative_weight = 0

            for proxy, weight in zip(available_proxies, weights):
                cumulative_weight += weight
                if r <= cumulative_weight:
                    return proxy

            return available_proxies[-1]

    async def acquire_proxy(self, proxy: str) -> bool:
        """프록시 사용 시작"""
        async with self.lock:
            if self.active_connections[proxy] < self.max_concurrent_per_proxy:
                self.active_connections[proxy] += 1
                self.proxy_stats[proxy].last_used = time.time()
                return True
            return False

    async def release_proxy(self, proxy: str):
        """프록시 사용 종료"""
        async with self.lock:
            if self.active_connections[proxy] > 0:
                self.active_connections[proxy] -= 1

    async def record_success(self, proxy: str, response_time: float):
        """성공 기록"""
        async with self.lock:
            stats = self.proxy_stats[proxy]
            stats.success_count += 1
            stats.total_response_time += response_time
            stats.avg_response_time = stats.total_response_time / stats.success_count

    async def record_failure(self, proxy: str):
        """실패 기록 (더 엄격한 기준)"""
        async with self.lock:
            stats = self.proxy_stats[proxy]
            stats.failure_count += 1

            # 실패율이 높으면 더 빠르게 제외 (기준 강화)
            if stats.failure_count > 5 and stats.success_rate < 0.5:  # 5회 실패 후 성공률 50% 미만
                self.failed_proxies.add(proxy)
                print(f"[WARNING] 프록시 일시 제외: {proxy.split(':')[0]} (성공률: {stats.success_rate:.2f})")
            elif stats.failure_count > 3:  # 3회 이상 실패시 경고
                print(f"[WARNING] 프록시 실패 증가: {proxy.split(':')[0]} (실패: {stats.failure_count}회)")

    def get_proxy_dict(self, proxy_string: str) -> Optional[Dict[str, str]]:
        """프록시 문자열을 aiohttp용 딕셔너리로 변환"""
        if not proxy_string:
            return None

        parts = proxy_string.split(':')
        if len(parts) == 2:  # ip:port
            ip, port = parts
            return f'http://{ip}:{port}'
        elif len(parts) == 4:  # ip:port:username:password
            ip, port, username, password = parts
            return f'http://{username}:{password}@{ip}:{port}'
        return None


class AsyncCoupangCrawler:
    """비동기 쿠팡 크롤러"""

    def __init__(self, proxy_list: List[str] = None, max_concurrent: int = 80):
        # 기본 설정 (높은 동시성 + 안전성)
        self.base_review_url = "https://www.coupang.com/vp/product/reviews"
        self.max_concurrent = min(max_concurrent, 80)  # 최대 80개 동시 요청
        self.max_pages_per_product = 100  # 페이지 수는 100개로 유지
        self.max_retries = 2  # 재시도 횟수는 2회로 유지

        # 비동기 관리자들 (프록시당 1개 연결)
        self.proxy_manager = AsyncProxyManager(proxy_list, max_concurrent_per_proxy=1)  # 프록시당 1개로 제한
        self.global_semaphore = asyncio.Semaphore(self.max_concurrent)

        # User-Agent 관리
        self.ua = NonWindowsUserAgent()

        # URL 관리
        self.url_manager = URLManager()

        # 통계
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0

        # SSL 컨텍스트 설정
        self.ssl_context = self._create_ssl_context()

    def _create_ssl_context(self):
        """SSL 검증을 비활성화한 SSL 컨텍스트 생성"""
        try:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            return ssl_context
        except Exception as e:
            print(f"[WARNING] SSL 컨텍스트 생성 실패: {e}")
            return False  # SSL 검증 완전 비활성화

    def get_realistic_headers(self) -> Dict[str, str]:
        """더욱 실제 브라우저와 유사한 헤더 생성"""
        user_agent = self.ua.random

        # 기본 브라우저 헤더 (실제 Chrome에서 복사)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "DNT": "1",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": user_agent,
        }

        # User-Agent에 따라 플랫폼 정보 조정
        if 'iPhone' in user_agent or 'iPad' in user_agent:
            headers.update({
                "sec-ch-ua-platform": '"iOS"',
                "sec-ch-ua-mobile": "?1" if 'iPhone' in user_agent else "?0"
            })
        elif 'Android' in user_agent:
            headers.update({
                "sec-ch-ua-platform": '"Android"',
                "sec-ch-ua-mobile": "?1"
            })
        elif 'Macintosh' in user_agent or 'Mac OS X' in user_agent:
            headers.update({
                "sec-ch-ua-platform": '"macOS"',
                "sec-ch-ua-mobile": "?0"
            })
        else:
            headers.update({
                "sec-ch-ua-platform": '"macOS"',
                "sec-ch-ua-mobile": "?0"
            })

        # 쿠팡 특화 헤더 (필요시에만)
        if random.choice([True, False]):
            headers.update({
                "x-coupang-target-market": "KR",
                "x-coupang-accept-language": "ko-KR",
            })

        # 랜덤 요소 추가 (50% 확률)
        if random.choice([True, False]):
            headers["Priority"] = "u=0, i"

        return headers

    async def make_request(self, session: aiohttp.ClientSession, url: str,
                           params: Dict, proxy: str) -> Optional[Tuple[str, float]]:
        """단일 HTTP 요청 수행"""
        start_time = time.time()

        try:
            proxy_url = self.proxy_manager.get_proxy_dict(proxy) if proxy else None

            # 요청 헤더에 추가 정보
            headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }

            async with session.get(
                    url,
                    params=params,
                    proxy=proxy_url,
                    ssl=self.ssl_context,  # 커스텀 SSL 컨텍스트 사용
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=True
            ) as response:
                response_time = time.time() - start_time

                if response.status == 200:
                    content = await response.text()
                    if proxy:
                        await self.proxy_manager.record_success(proxy, response_time)
                    return content, response_time
                elif response.status == 403:
                    print(f"[WARNING] HTTP 403 - 프록시 차단: {proxy.split(':')[0] if proxy else 'No proxy'}")
                    if proxy:
                        await self.proxy_manager.record_failure(proxy)
                    return None, response_time
                else:
                    print(f"[WARNING] HTTP {response.status}")
                    if proxy:
                        await self.proxy_manager.record_failure(proxy)
                    return None, response_time

        except asyncio.TimeoutError:
            if proxy:
                await self.proxy_manager.record_failure(proxy)
            print(f"[ERROR] 타임아웃: {proxy.split(':')[0] if proxy else 'No proxy'}")
            return None, time.time() - start_time
        except ssl.SSLError as e:
            if proxy:
                await self.proxy_manager.record_failure(proxy)
            print(f"[ERROR] SSL 오류: {e}")
            return None, time.time() - start_time
        except Exception as e:
            if proxy:
                await self.proxy_manager.record_failure(proxy)
            print(f"[ERROR] 요청 실패: {e}")
            return None, time.time() - start_time

    async def fetch_page_with_retry(self, session: aiohttp.ClientSession,
                                    payload: Dict, max_retries: int = 2) -> Optional[str]:
        """재시도가 포함된 페이지 요청 (보수적 접근)"""
        async with self.global_semaphore:

            # 프록시 실패율이 높으면 프록시 없이 시도 (기준 강화: 80% → 70%)
            proxy_failure_rate = len(self.proxy_manager.failed_proxies) / max(len(self.proxy_manager.proxy_list),
                                                                              1) if self.proxy_manager.proxy_list else 0
            use_proxy = proxy_failure_rate < 0.7  # 70% 이상 실패하면 프록시 사용 안함

            if proxy_failure_rate > 0.5:  # 50% 이상 실패시 경고
                print(f"[WARNING] 프록시 실패율 {proxy_failure_rate:.1%} - 직접 연결 가능성 증가")

            for attempt in range(max_retries):
                if use_proxy and self.proxy_manager.proxy_list:
                    # 프록시 사용 시도
                    proxy = await self.proxy_manager.get_best_proxy()

                    if proxy and await self.proxy_manager.acquire_proxy(proxy):
                        try:
                            result, response_time = await self.make_request(
                                session, self.base_review_url, payload, proxy
                            )

                            if result:
                                self.successful_requests += 1
                                return result
                            else:
                                self.failed_requests += 1

                        finally:
                            await self.proxy_manager.release_proxy(proxy)
                    else:
                        # 사용 가능한 프록시가 없으면 프록시 없이 시도
                        use_proxy = False

                if not use_proxy:
                    # 프록시 없이 직접 요청
                    print(f"[DEBUG] 프록시 없이 직접 요청 시도... (시도 {attempt + 1}/{max_retries})")
                    result, response_time = await self.make_request(
                        session, self.base_review_url, payload, None
                    )

                    if result:
                        self.successful_requests += 1
                        return result
                    else:
                        self.failed_requests += 1

                # 재시도 전 대기 (더 긴 딜레이)
                if attempt < max_retries - 1:
                    delay = random.uniform(3, 7)  # 3-7초 대기 (기존 2-5초에서 증가)
                    print(f"[DEBUG] 재시도 전 {delay:.1f}초 대기...")
                    await asyncio.sleep(delay)

            self.total_requests += 1
            return None

    async def parse_review_page(self, html_content: str, page_num: int,
                                sd: SaveData, product_title: str) -> int:
        """리뷰 페이지 파싱 및 저장"""
        try:
            soup = bs(html_content, "html.parser")
            articles = soup.select("article.sdp-review__article__list")

            if not articles:
                return 0

            print(f"[SUCCESS] 페이지 {page_num}에서 {len(articles)}개 리뷰 발견")

            # 리뷰 데이터 파싱
            reviews_data = []
            for article in articles:
                review_data = self.extract_review_data(article, product_title)
                if review_data:
                    reviews_data.append(review_data)

            # 배치로 저장 (Thread pool 사용하여 I/O 블로킹 방지)
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=2) as executor:
                for review_data in reviews_data:
                    await loop.run_in_executor(executor, sd.save, review_data)

            return len(reviews_data)

        except Exception as e:
            print(f"[ERROR] 페이지 {page_num} 파싱 실패: {e}")
            return 0

    def extract_review_data(self, article, product_title: str) -> Optional[Dict]:
        """단일 리뷰 데이터 추출 (기존 로직 유지)"""
        try:
            # 기존 추출 로직과 동일
            review_date_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__reg-date"
            )
            review_date = review_date_elem.text.strip() if review_date_elem else "-"

            user_name_elem = article.select_one(
                "span.sdp-review__article__list__info__user__name"
            )
            user_name = user_name_elem.text.strip() if user_name_elem else "-"

            rating_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__star-orange"
            )
            if rating_elem and rating_elem.get("data-rating"):
                try:
                    rating = int(rating_elem.get("data-rating"))
                except (ValueError, TypeError):
                    rating = 0
            else:
                rating = 0

            prod_name_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__name"
            )
            prod_name = prod_name_elem.text.strip() if prod_name_elem else "-"

            headline_elem = article.select_one(
                "div.sdp-review__article__list__headline"
            )
            headline = headline_elem.text.strip() if headline_elem else "등록된 헤드라인이 없습니다"

            review_content_elem = article.select_one(
                "div.sdp-review__article__list__review__content.js_reviewArticleContent"
            )
            if review_content_elem:
                review_content = re.sub("[\n\t]", "", review_content_elem.text.strip())
            else:
                review_content_elem = article.select_one(
                    "div.sdp-review__article__list__review > div"
                )
                if review_content_elem:
                    review_content = re.sub("[\n\t]", "", review_content_elem.text.strip())
                else:
                    review_content = "등록된 리뷰내용이 없습니다"

            helpful_count_elem = article.select_one("span.js_reviewArticleHelpfulCount")
            helpful_count = helpful_count_elem.text.strip() if helpful_count_elem else "0"

            review_images = article.select("div.sdp-review__article__list__attachment__list img")
            image_count = len(review_images)

            return {
                "title": product_title,
                "prod_name": prod_name,
                "review_date": review_date,
                "user_name": user_name,
                "rating": rating,
                "headline": headline,
                "review_content": review_content,
                "helpful_count": helpful_count,
                "image_count": image_count
            }

        except Exception as e:
            print(f"[ERROR] 리뷰 데이터 추출 실패: {e}")
            return None

    async def crawl_product_pages_batch(self, prod_code: str, product_title: str,
                                        sd: SaveData, batch_size: int = 5) -> int:
        """상품의 여러 페이지를 배치로 크롤링 (보수적 접근)"""

        # SSL 검증 비활성화된 커넥터 설정
        connector = aiohttp.TCPConnector(
            limit=100,  # 전체 연결 풀 크기 증가
            limit_per_host=80,  # 호스트당 연결 수 증가 (80개 동시 요청 지원)
            ssl=self.ssl_context,
            enable_cleanup_closed=True,
            force_close=True
        )
        timeout = aiohttp.ClientTimeout(total=45)  # 타임아웃 유지

        async with aiohttp.ClientSession(
                headers=self.get_realistic_headers(),
                connector=connector,
                timeout=timeout
        ) as session:

            total_reviews = 0
            current_page = 1
            consecutive_empty_pages = 0
            max_empty_pages = 3  # 빈 페이지 허용 횟수 감소
            failed_proxy_count = 0
            max_failed_proxies = len(self.proxy_manager.proxy_list) * 0.9 if self.proxy_manager.proxy_list else 0

            while (consecutive_empty_pages < max_empty_pages and
                   current_page <= self.max_pages_per_product):

                # 프록시 대부분이 실패했으면 중단
                if self.proxy_manager.proxy_list and failed_proxy_count > max_failed_proxies:
                    print(f"[WARNING] 90% 이상의 프록시가 차단되어 크롤링을 중단합니다.")
                    break

                # 배치 단위로 페이지 요청 생성 (더 작은 배치)
                end_page = min(current_page + batch_size - 1, self.max_pages_per_product)
                batch_tasks = []

                for page_num in range(current_page, end_page + 1):
                    payload = {
                        "productId": str(prod_code),
                        "page": str(page_num),
                        "size": "5",
                        "sortBy": "ORDER_SCORE_ASC",
                        "ratings": "",
                        "q": "",
                        "viRoleCode": "2",
                        "ratingSummary": "true",
                    }

                    task = self.fetch_page_with_retry(session, payload, max_retries=2)
                    batch_tasks.append((page_num, task))

                    # 요청 간 짧은 딜레이 (봇 탐지 방지)
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                # 배치 실행
                print(f"[INFO] 페이지 {current_page}-{end_page} 배치 요청 중... (보수적 모드)")
                batch_results = await asyncio.gather(
                    *[task for _, task in batch_tasks],
                    return_exceptions=True
                )

                # 결과 처리
                batch_review_count = 0
                batch_403_count = 0

                for (page_num, _), result in zip(batch_tasks, batch_results):
                    if isinstance(result, Exception):
                        print(f"[ERROR] 페이지 {page_num} 요청 실패: {result}")
                        continue

                    if result:
                        review_count = await self.parse_review_page(
                            result, page_num, sd, product_title
                        )
                        batch_review_count += review_count

                        if review_count == 0:
                            consecutive_empty_pages += 1
                        else:
                            consecutive_empty_pages = 0
                    else:
                        consecutive_empty_pages += 1
                        batch_403_count += 1

                # 403 오류가 많으면 실패한 프록시 카운트 증가
                if batch_403_count > len(batch_tasks) * 0.7:
                    failed_proxy_count += batch_403_count

                total_reviews += batch_review_count
                current_page = end_page + 1

                # 배치 간 더 긴 대기 (인간적인 패턴)
                if current_page <= self.max_pages_per_product:
                    delay = random.uniform(3, 8)  # 3-8초 대기
                    print(f"[DEBUG] 다음 배치까지 {delay:.1f}초 대기... (탐지 방지)")
                    await asyncio.sleep(delay)

                print(
                    f"[BATCH] 페이지 {current_page - batch_size}-{end_page}: {batch_review_count}개 리뷰, 403 오류: {batch_403_count}개")

                # 연속으로 모든 요청이 실패하면 조기 종료
                if batch_review_count == 0 and batch_403_count == len(batch_tasks):
                    consecutive_empty_pages += 1
                    print(f"[WARNING] 배치 전체가 차단되었습니다. 연속 실패: {consecutive_empty_pages}/{max_empty_pages}")

            return total_reviews

    async def crawl_single_product(self, url: str, product_name: str) -> bool:
        """단일 상품 크롤링 (기존 인터페이스 유지)"""
        if '#' in url:
            url = url.split('#')[0]

        # 상품 코드 추출 (기존 로직)
        prod_code = url.split("products/")[-1].split("?")[0]
        print(f"[DEBUG] 상품 코드: {prod_code}")

        # SaveData 인스턴스 생성
        sd = SaveData()

        product_start_time = time.time()

        try:
            total_reviews = await self.crawl_product_pages_batch(
                prod_code, product_name, sd
            )

            product_end_time = time.time()
            product_elapsed = product_end_time - product_start_time

            print(f"\n[PRODUCT SUMMARY] 상품 '{product_name}' 크롤링 완료")
            print(f"[INFO] 총 리뷰 수: {total_reviews}개")
            print(f"[INFO] 소요 시간: {product_elapsed / 60:.1f}분")
            print(
                f"[INFO] 성공률: {self.successful_requests}/{self.total_requests} ({self.successful_requests / max(self.total_requests, 1) * 100:.1f}%)")

            return total_reviews > 0

        except Exception as e:
            print(f"[ERROR] 상품 크롤링 실패: {e}")
            return False

    async def start_async(self) -> None:
        """비동기 크롤링 시작 (프록시당 1개 연결 모드)"""
        print("=" * 70)
        print("🚀 쿠팡 리뷰 크롤러 v2.2 (프록시 분산 모드)")
        print("=" * 70)

        # JSON 파일 로드
        if not self.url_manager.load_urls_from_json():
            print("[ERROR] JSON 파일을 로드할 수 없습니다.")
            return

        total_products = len(self.url_manager.products)
        print(f"[INFO] 총 {total_products}개 상품을 효율적으로 크롤링합니다.")
        print(f"[INFO] 최대 동시 요청 수: {self.max_concurrent}개")
        print(f"[INFO] 배치 크기: 5페이지 (안전성 유지)")
        print(f"[INFO] 상품당 최대 페이지: {self.max_pages_per_product}페이지")
        print(f"[INFO] 상품 간 대기시간: 15-30초")

        if self.proxy_manager.proxy_list:
            print(f"[INFO] 사용 가능한 프록시: {len(self.proxy_manager.proxy_list)}개")
            print(f"[INFO] 프록시당 동시 연결: {self.proxy_manager.max_concurrent_per_proxy}개 (차단 방지)")
            print(f"[STRATEGY] 더 많은 프록시를 동시 활용하여 처리량 최대화")
            print(f"[WARNING] 프록시 70% 이상 실패시 자동으로 직접 연결로 전환됩니다.")
        else:
            print(f"[WARNING] 프록시 없이 실행 - 매우 느린 속도로 진행됩니다.")

        print("=" * 70)

        # 전체 통계
        total_success_products = 0
        total_failed_products = 0
        overall_start_time = time.time()

        # 상품별 크롤링 실행
        for i, product in enumerate(self.url_manager.products, 1):
            print(f"\n{'=' * 20} 상품 {i}/{total_products} {'=' * 20}")
            print(f"[INFO] 현재 상품: {product['name']}")
            print(f"[INFO] 상품 URL: {product['url']}")

            try:
                success = await self.crawl_single_product(product['url'], product['name'])
                if success:
                    total_success_products += 1
                    print(f"✅ 상품 {i} 크롤링 성공")
                else:
                    total_failed_products += 1
                    print(f"❌ 상품 {i} 크롤링 실패")

            except KeyboardInterrupt:
                print(f"\n[INFO] 사용자에 의해 중단되었습니다.")
                break
            except Exception as e:
                print(f"[ERROR] 상품 크롤링 중 예외 발생: {e}")
                total_failed_products += 1
                continue

            # 상품 간 대기 시간 (더 긴 딜레이)
            if i < total_products:
                delay = random.uniform(15, 30)  # 15-30초 대기 (매우 보수적)
                print(f"[INFO] 다음 상품까지 {delay:.1f}초 대기... (봇 탐지 방지)")
                await asyncio.sleep(delay)

        # 전체 결과 요약
        overall_end_time = time.time()
        total_elapsed = overall_end_time - overall_start_time

        print("\n" + "=" * 70)
        print("📊 전체 크롤링 결과 요약")
        print("=" * 70)
        print(f"총 상품 수: {total_products}개")
        print(f"성공한 상품: {total_success_products}개")
        print(f"실패한 상품: {total_failed_products}개")
        print(f"성공률: {(total_success_products / total_products * 100):.1f}%")
        print(f"총 소요 시간: {total_elapsed / 60:.1f}분")
        print(f"총 요청 수: {self.total_requests}개")
        print(f"요청 성공률: {(self.successful_requests / max(self.total_requests, 1) * 100):.1f}%")
        print(f"📁 결과 파일들은 'Coupang-reviews' 폴더에서 확인하세요.")
        print("=" * 70)


def start_optimized_crawler():
    """최적화된 크롤러 실행 함수"""

    # 프록시 목록 로드
    proxy_file_path = "proxy_list.txt"
    print("=" * 70)
    print("🔗 프록시 설정 (보수적 모드)")
    print("=" * 70)

    proxy_list = load_proxy_list_from_file(proxy_file_path)

    if not proxy_list:
        print(f"\n[WARNING] {proxy_file_path} 파일에 유효한 프록시가 없습니다.")
        run_without_proxy = input("프록시 없이 실행하시겠습니까? (Y/n): ").lower().strip()
        if run_without_proxy == 'n':
            print("[INFO] 프로그램을 종료합니다.")
            return
        proxy_list = None
    else:
        print(f"\n[INFO] {len(proxy_list)}개의 프록시가 준비되었습니다.")
        print(f"[NOTICE] 최근 쿠팡에서 프록시 차단이 강화되었습니다.")
        print(f"[NOTICE] 403 오류가 많이 발생하면 프록시 없이 자동 전환됩니다.")

        use_proxy = input("프록시를 사용하시겠습니까? (Y/n): ").lower().strip()
        if use_proxy == 'n':
            proxy_list = None

    # 동시성 설정 (프록시당 1개 연결)
    if proxy_list:
        max_concurrent = min(80, len(proxy_list))  # 프록시 수만큼, 최대 80개
        print(f"[INFO] 프록시 활용 모드 - 최대 동시 요청: {max_concurrent}개")
        print(f"[INFO] 프록시당 연결 제한: 1개 (차단 방지)")
        print(f"[INFO] 배치 크기: 5페이지 (안전성 유지)")
        print(f"[INFO] 총 {len(proxy_list)}개 프록시를 순환 활용")
        print(f"[INFO] 요청 간 딜레이: 3-8초 (봇 탐지 방지)")
        print(f"[INFO] SSL 검증 비활성화로 프록시 호환성 확보")
    else:
        max_concurrent = 3  # 프록시 없이는 매우 보수적으로 설정
        print(f"[INFO] 프록시 없이 최대 동시 요청: {max_concurrent}개")
        print(f"[WARNING] 프록시 없이 실행하면 IP 차단 위험이 높습니다.")
        print(f"[WARNING] 매우 느린 속도로 크롤링됩니다. (안전성 우선)")

    # 크롤러 생성 및 실행
    crawler = AsyncCoupangCrawler(proxy_list=proxy_list, max_concurrent=max_concurrent)

    try:
        # 비동기 실행
        asyncio.run(crawler.start_async())
        print("\n✅ 모든 상품 크롤링이 완료되었습니다!")

    except KeyboardInterrupt:
        print("\n[INFO] 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n[ERROR] 프로그램 실행 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 쿠팡 리뷰 크롤러 v2.2 (프록시 분산 모드)")
    print("=" * 70)
    print("⚡ 프록시당 1개 연결로 최대 80개 동시 요청")
    print("🔐 SSL 검증 비활성화로 프록시 호환성 확보")
    print("🎯 많은 프록시를 동시 활용하여 처리량 최대화")
    print("🛡️ 연결 제한으로 개별 프록시 차단 위험 최소화")
    print("📊 배치 크기 5개로 안정성과 효율성 균형")
    print("=" * 70)
    start_optimized_crawler()
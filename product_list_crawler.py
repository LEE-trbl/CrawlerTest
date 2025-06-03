#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
쿠팡 곰곰 브랜드 실시간 크롤링 시스템
동적 페이지 처리 및 대용량 데이터 수집
"""

import csv
import json
import logging
import random
import re
import time
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup, Tag

from selenium import webdriver
from selenium.webdriver.chrome.options import ChromiumOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, NoSuchElementException

SELENIUM_AVAILABLE = True


# =================== 설정 및 데이터 클래스 ===================
@dataclass
class CrawlingConfig:
    """크롤링 설정"""
    base_url: str = "https://www.coupang.com"
    brand_url: str = "https://www.coupang.com/np/products/brand-shop"
    brand_name: str = "홈플래닛"
    max_pages: int = 5
    delay_range: tuple = (2.0, 5.0)
    max_retries: int = 3
    timeout: int = 30

    # 출력 설정
    output_dir: str = "./coupang_홈플래닛_data"
    csv_filename: str = "홈플래닛_products_{timestamp}.csv"
    json_filename: str = "홈플래닛_products_{timestamp}.json"

    # 로깅 설정
    log_level: str = "INFO"

    # Selenium 설정
    headless: bool = True
    window_size: tuple = (1920, 1080)

    # User-Agent 목록
    user_agents: List[str] = None

    def __post_init__(self):
        if self.user_agents is None:
            self.user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ]


@dataclass
class ProductData:
    """상품 데이터 구조"""
    product_id: str
    product_name: str
    price: str
    original_price: str
    discount_rate: str
    unit_price: str
    rating: str
    review_count: str
    product_url: str
    image_url: str
    delivery_info: str
    cashback_amount: str
    is_rocket_delivery: bool
    vendor_item_id: str
    item_id: str
    page_number: int
    crawled_at: str


# =================== 로깅 설정 ===================
class LoggerManager:
    """로깅 관리 클래스"""

    @staticmethod
    def setup_logger(config: CrawlingConfig) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger('coupang_live_crawler')
        logger.setLevel(getattr(logging, config.log_level))

        # 기존 핸들러 제거
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # 콘솔 핸들러
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)

        # 로그 디렉토리 생성
        log_dir = Path(config.output_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # 파일 핸들러
        file_handler = logging.FileHandler(
            log_dir / f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # 포맷터
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

        return logger


# =================== 세션 관리 클래스 ===================
class SessionManager:
    """HTTP 세션 관리"""

    def __init__(self, config: CrawlingConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """세션 생성"""
        session = requests.Session()

        # 기본 헤더 설정
        session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': random.choice(self.config.user_agents)
        })

        return session

    def get_with_retry(self, url: str, **kwargs) -> Optional[requests.Response]:
        """재시도 로직이 포함된 GET 요청"""
        for attempt in range(self.config.max_retries):
            try:
                # User-Agent 로테이션
                self.session.headers['User-Agent'] = random.choice(self.config.user_agents)

                response = self.session.get(
                    url,
                    timeout=self.config.timeout,
                    **kwargs
                )

                if response.status_code == 200:
                    return response
                else:
                    self.logger.warning(f"HTTP {response.status_code}: {url}")

            except requests.RequestException as e:
                self.logger.warning(f"요청 실패 (시도 {attempt + 1}/{self.config.max_retries}): {e}")
                if attempt < self.config.max_retries - 1:
                    time.sleep(random.uniform(1, 3))

        return None


# =================== Selenium 드라이버 관리 ===================
class SeleniumDriverManager:
    """Selenium 드라이버 관리"""

    def __init__(self, config: CrawlingConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.driver = None
        self.wait = None

        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium이 설치되지 않았습니다. pip install selenium으로 설치하세요.")

    def setup_driver(self):
        """Chrome 드라이버 설정"""
        try:
            options = ChromiumOptions()

            # 기본 옵션
            if self.config.headless:
                options.add_argument('--headless')

            options.add_argument(f'--window-size={self.config.window_size[0]},{self.config.window_size[1]}')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')

            # 디텍션 방지
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            # 리소스 절약
            prefs = {
                "profile.managed_default_content_settings.images": 2,  # 이미지 로딩 비활성화
                "profile.default_content_setting_values.notifications": 2,
                "profile.managed_default_content_settings.plugins": 2,
            }
            options.add_experimental_option("prefs", prefs)

            # User-Agent 설정
            options.add_argument(f'--user-agent={random.choice(self.config.user_agents)}')

            self.driver = webdriver.Chrome(options=options)

            # WebDriver 탐지 방지 스크립트
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            self.wait = WebDriverWait(self.driver, self.config.timeout)

            self.logger.info("Chrome 드라이버 설정 완료")

        except Exception as e:
            self.logger.error(f"드라이버 설정 실패: {e}")
            raise

    def navigate_to_page(self, url: str, page: int = 1) -> bool:
        """페이지 이동"""
        try:
            full_url = f"{url}?brandName={self.config.brand_name}&page={page}"
            self.logger.info(f"페이지 이동: {full_url}")

            self.driver.get(full_url)

            # 페이지 로딩 대기
            self.wait.until(
                EC.presence_of_element_located((By.ID, "productList"))
            )

            # 추가 로딩 대기
            time.sleep(random.uniform(*self.config.delay_range))

            return True

        except TimeoutException:
            self.logger.error(f"페이지 로딩 타임아웃: {url}")
            return False
        except Exception as e:
            self.logger.error(f"페이지 이동 실패: {e}")
            return False

    def scroll_and_load_content(self) -> str:
        """스크롤하여 모든 콘텐츠 로드"""
        self.logger.info("페이지 스크롤 시작")

        last_height = self.driver.execute_script("return document.body.scrollHeight")
        no_change_count = 0

        while no_change_count < 3:
            # 스크롤 다운
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            # 로딩 대기
            time.sleep(random.uniform(2, 4))

            # 새로운 높이 확인
            new_height = self.driver.execute_script("return document.body.scrollHeight")

            if new_height == last_height:
                no_change_count += 1
            else:
                no_change_count = 0
                last_height = new_height

        # 최종 페이지 소스 반환
        return self.driver.page_source

    def close(self):
        """드라이버 종료"""
        if self.driver:
            self.driver.quit()
            self.logger.info("드라이버 종료")


# =================== 데이터 추출 클래스 ===================
class CoupangDataExtractor:
    """쿠팡 데이터 추출"""

    def __init__(self, config: CrawlingConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger

    def clean_text(self, text: str) -> str:
        """텍스트 정제"""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text.strip())
        return text

    def extract_number(self, text: str) -> str:
        """숫자 추출"""
        if not text:
            return ""
        numbers = re.findall(r'[\d,]+', text)
        return numbers[0] if numbers else ""

    def extract_products_from_html(self, html: str, page_number: int) -> List[ProductData]:
        """HTML에서 상품 데이터 추출"""
        self.logger.info(f"페이지 {page_number} 데이터 추출 시작")

        soup = BeautifulSoup(html, 'html.parser')

        # 상품 리스트 찾기
        product_list = soup.find('ul', id='productList')
        if not product_list:
            self.logger.warning("상품 리스트를 찾을 수 없습니다.")
            return []

        # 개별 상품 요소들
        product_elements = product_list.find_all('li', class_='baby-product')
        self.logger.info(f"페이지 {page_number}에서 {len(product_elements)}개 상품 발견")

        products = []
        for i, element in enumerate(product_elements, 1):
            product_data = self._extract_single_product(element, page_number)
            if product_data:
                products.append(product_data)
                self.logger.debug(f"[{page_number}-{i:2d}] {product_data.product_name[:40]}...")

        self.logger.info(f"페이지 {page_number}에서 {len(products)}개 상품 추출 완료")
        return products

    def _extract_single_product(self, element: Tag, page_number: int) -> Optional[ProductData]:
        """개별 상품 데이터 추출"""
        try:
            # 기본 정보
            product_id = element.get('id', '')
            vendor_item_id = element.get('data-vendor-item-id', '')

            # 상품 링크
            product_link = element.find('a', class_='baby-product-link')
            if not product_link:
                return None

            item_id = product_link.get('data-item-id', '')
            product_url = urljoin(self.config.base_url, product_link.get('href', ''))

            # 상품명
            name_element = element.find('div', class_='name')
            product_name = self.clean_text(name_element.get_text() if name_element else "")

            # 가격 정보
            price_info = self._extract_price_info(element)

            # 평점 및 리뷰
            rating_info = self._extract_rating_info(element)

            # 이미지 URL
            img_element = element.find('img')
            image_url = img_element.get('src', '') if img_element else ""

            # 배송 정보
            delivery_element = element.find('span', class_='arrival-info')
            delivery_info = self.clean_text(delivery_element.get_text() if delivery_element else "")

            # 로켓배송 여부
            is_rocket = bool(element.find('span', class_='badge rocket'))

            # 적립금
            cashback_element = element.find('span', class_='reward-cash-txt')
            cashback_amount = self.clean_text(cashback_element.get_text() if cashback_element else "")

            return ProductData(
                product_id=product_id,
                product_name=product_name,
                price=price_info['current_price'],
                original_price=price_info['original_price'],
                discount_rate=price_info['discount_rate'],
                unit_price=price_info['unit_price'],
                rating=rating_info['rating'],
                review_count=rating_info['review_count'],
                product_url=product_url,
                image_url=image_url,
                delivery_info=delivery_info,
                cashback_amount=cashback_amount,
                is_rocket_delivery=is_rocket,
                vendor_item_id=vendor_item_id,
                item_id=item_id,
                page_number=page_number,
                crawled_at=datetime.now().isoformat()
            )

        except Exception as e:
            self.logger.error(f"상품 데이터 추출 실패: {e}")
            return None

    def _extract_price_info(self, element: Tag) -> Dict[str, str]:
        """가격 정보 추출"""
        price_info = {
            'current_price': '',
            'original_price': '',
            'discount_rate': '',
            'unit_price': ''
        }

        # 현재 가격
        price_element = element.find('strong', class_='price-value')
        if price_element:
            price_info['current_price'] = self.extract_number(price_element.get_text())

        # 할인율
        discount_element = element.find('span', class_='discount-percentage')
        if discount_element:
            price_info['discount_rate'] = discount_element.get_text().strip()

        # 원가
        original_price_element = element.find('del', class_='base-price')
        if original_price_element:
            price_info['original_price'] = self.extract_number(original_price_element.get_text())

        # 단위가격
        unit_price_element = element.find('span', class_='unit-price')
        if unit_price_element:
            price_info['unit_price'] = self.clean_text(unit_price_element.get_text())

        return price_info

    def _extract_rating_info(self, element: Tag) -> Dict[str, str]:
        """평점 및 리뷰 정보 추출"""
        rating_info = {
            'rating': '',
            'review_count': ''
        }

        # 평점
        rating_element = element.find('em', class_='rating')
        if rating_element:
            style = rating_element.get('style', '')
            width_match = re.search(r'width:(\d+)%', style)
            if width_match:
                width_percent = int(width_match.group(1))
                rating_info['rating'] = str(width_percent / 20)

        # 리뷰 수
        review_count_element = element.find('span', class_='rating-total-count')
        if review_count_element:
            review_text = review_count_element.get_text()
            review_count = re.sub(r'[^\d,]', '', review_text)
            rating_info['review_count'] = review_count

        return rating_info


# =================== 데이터 저장 클래스 ===================
class DataStorage:
    """데이터 저장 관리"""

    def __init__(self, config: CrawlingConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_to_csv(self, products: List[ProductData]) -> str:
        """CSV 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self.config.csv_filename.format(timestamp=timestamp)
        filepath = self.output_dir / filename

        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            headers = [
                '상품ID', '상품명', '현재가격', '정가', '할인율', '단위가격',
                '평점', '리뷰수', '상품URL', '이미지URL', '배송정보',
                '적립금', '로켓배송여부', '판매자상품ID', '아이템ID',
                '페이지번호', '수집시간'
            ]

            writer = csv.writer(csvfile)
            writer.writerow(headers)

            for product in products:
                row = [
                    product.product_id, product.product_name, product.price,
                    product.original_price, product.discount_rate, product.unit_price,
                    product.rating, product.review_count, product.product_url,
                    product.image_url, product.delivery_info, product.cashback_amount,
                    product.is_rocket_delivery, product.vendor_item_id, product.item_id,
                    product.page_number, product.crawled_at
                ]
                writer.writerow(row)

        self.logger.info(f"CSV 저장 완료: {filepath} ({len(products)}개 상품)")
        return str(filepath)

    def save_to_json(self, products: List[ProductData]) -> str:
        """JSON 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = self.config.json_filename.format(timestamp=timestamp)
        filepath = self.output_dir / filename

        products_dict = [asdict(product) for product in products]

        with open(filepath, 'w', encoding='utf-8') as jsonfile:
            json.dump(products_dict, jsonfile, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON 저장 완료: {filepath}")
        return str(filepath)


# =================== 메인 크롤러 클래스 ===================
class Coupang홈플래닛Crawler:
    """쿠팡 곰곰 브랜드 크롤러"""

    def __init__(self, config: CrawlingConfig = None):
        self.config = config or CrawlingConfig()
        self.logger = LoggerManager.setup_logger(self.config)
        self.session_manager = SessionManager(self.config, self.logger)
        self.driver_manager = SeleniumDriverManager(self.config, self.logger)
        self.data_extractor = CoupangDataExtractor(self.config, self.logger)
        self.storage = DataStorage(self.config, self.logger)

        self.all_products = []

    def run_crawling(self) -> Dict[str, Any]:
        """크롤링 실행"""
        self.logger.info(f"🚀 쿠팡 '{self.config.brand_name}' 브랜드 크롤링 시작")
        self.logger.info(f"📊 수집 예정 페이지: {self.config.max_pages}개")

        start_time = datetime.now()

        try:
            # Selenium 드라이버 설정
            self.driver_manager.setup_driver()

            # 페이지별 크롤링
            for page in range(1, self.config.max_pages + 1):
                self.logger.info(f"📄 페이지 {page}/{self.config.max_pages} 크롤링 시작")

                success = self._crawl_single_page(page)
                if not success:
                    self.logger.warning(f"페이지 {page} 크롤링 실패, 건너뜀")
                    continue

                # 페이지 간 딜레이
                if page < self.config.max_pages:
                    delay = random.uniform(*self.config.delay_range)
                    self.logger.info(f"⏳ {delay:.1f}초 대기 중...")
                    time.sleep(delay)

            # 데이터 저장
            if self.all_products:
                csv_path = self.storage.save_to_csv(self.all_products)
                json_path = self.storage.save_to_json(self.all_products)

                execution_time = datetime.now() - start_time

                result = {
                    'status': 'success',
                    'total_products': len(self.all_products),
                    'pages_crawled': self.config.max_pages,
                    'csv_file': csv_path,
                    'json_file': json_path,
                    'execution_time': str(execution_time),
                    'products_per_page': self._get_products_per_page_stats()
                }

                self.logger.info(f"✅ 크롤링 완료! 총 {len(self.all_products)}개 상품 수집")
                self.logger.info(f"⏱️  실행 시간: {execution_time}")

                return result
            else:
                return {
                    'status': 'error',
                    'message': '수집된 상품이 없습니다.'
                }

        except Exception as e:
            self.logger.error(f"❌ 크롤링 실패: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
        finally:
            self.driver_manager.close()

    def _crawl_single_page(self, page: int) -> bool:
        """단일 페이지 크롤링"""
        try:
            # 페이지 이동
            success = self.driver_manager.navigate_to_page(
                self.config.brand_url, page
            )
            if not success:
                return False

            # 콘텐츠 로드
            html_content = self.driver_manager.scroll_and_load_content()

            # 데이터 추출
            products = self.data_extractor.extract_products_from_html(html_content, page)

            # 결과 저장
            self.all_products.extend(products)

            self.logger.info(f"✅ 페이지 {page} 완료: {len(products)}개 상품 추출")
            return True

        except Exception as e:
            self.logger.error(f"페이지 {page} 크롤링 오류: {e}")
            return False

    def _get_products_per_page_stats(self) -> Dict[int, int]:
        """페이지별 상품 수 통계"""
        stats = {}
        for product in self.all_products:
            page = product.page_number
            stats[page] = stats.get(page, 0) + 1
        return stats


# =================== 실행 함수 ===================
def main():
    """메인 실행 함수"""
    print("🛒 쿠팡 곰곰 브랜드 크롤링 시스템")
    print("=" * 50)

    # Selenium 설치 확인
    if not SELENIUM_AVAILABLE:
        print("❌ Selenium이 설치되지 않았습니다.")
        print("📦 설치 명령어: pip install selenium")
        print("🔧 Chrome 드라이버도 필요합니다: https://chromedriver.chromium.org/")
        return

    # 설정
    config = CrawlingConfig(
        max_pages=3,  # 테스트용으로 3페이지만
        headless=False,  # 브라우저 창 표시 (디버깅용)
        delay_range=(1.0, 1.1),
        log_level="INFO"
    )

    print(f"🎯 브랜드: {config.brand_name}")
    print(f"📄 수집 페이지: {config.max_pages}개")
    print(f"💾 출력 폴더: {config.output_dir}")
    print("-" * 50)

    # 크롤링 실행
    crawler = Coupang홈플래닛Crawler(config)
    result = crawler.run_crawling()

    # 결과 출력
    print("\n" + "=" * 50)
    if result['status'] == 'success':
        print("🎉 크롤링 성공!")
        print(f"📊 총 상품 수: {result['total_products']:,}개")
        print(f"📁 CSV 파일: {result['csv_file']}")
        print(f"📁 JSON 파일: {result['json_file']}")
        print(f"⏱️ 실행 시간: {result['execution_time']}")

        print("\n📈 페이지별 상품 수:")
        for page, count in result['products_per_page'].items():
            print(f"  페이지 {page}: {count:,}개")
    else:
        print(f"❌ 크롤링 실패: {result['message']}")


if __name__ == "__main__":
    main()
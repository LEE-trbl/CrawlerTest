import scrapy
import re
import time
import random
from bs4 import BeautifulSoup as bs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from coupang_reviews_scrapy.items import CoupangReviewItem


class CoupangReviewSpider(scrapy.Spider):
    name = 'coupang_review'
    allowed_domains = ['coupang.com']

    custom_settings = {
        'COOKIES_ENABLED': True,
        'DOWNLOAD_DELAY': 3,
        'RANDOMIZE_DOWNLOAD_DELAY': 1.0,
        'HTTPERROR_ALLOWED_CODES': [403, 404],
    }

    def __init__(self, url=None, *args, **kwargs):
        super(CoupangReviewSpider, self).__init__(*args, **kwargs)

        if not url:
            raise ValueError(
                "URL 파라미터가 필요합니다. 예: scrapy crawl coupang_review -a url='https://www.coupang.com/vp/products/...'")

        self.start_url = url
        self.base_review_url = "https://www.coupang.com/vp/product/reviews"
        self.product_code = self.get_product_code(url)
        self.product_title = None
        self.page_title = None

        # Selenium 드라이버 설정
        self.setup_selenium()

        # 더 현실적인 헤더 설정
        self.headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-encoding": "gzip, deflate, br",
            "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "max-age=0",
            "connection": "keep-alive",
            "upgrade-insecure-requests": "1",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

    def setup_selenium(self):
        """Selenium WebDriver 설정 - 더 현실적인 브라우저 시뮬레이션"""
        options = Options()

        # 헤드리스 모드 완전히 끄기 (디버깅용)
        # options.add_argument("--headless")  # 주석 처리하여 실제 브라우저 창 보기

        # 기본 보안 설정
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)

        # 더 현실적인 브라우저 설정
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        options.add_argument("--accept-lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7")

        # 추가 안정성 설정
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins")
        options.add_argument("--disable-images")  # 이미지 로딩 비활성화로 속도 향상
        options.add_argument("--disable-javascript")  # JS 비활성화로 탐지 회피

        # 창 크기 설정
        options.add_argument("--window-size=1920,1080")

        try:
            # webdriver-manager 사용 (자동 드라이버 관리) - Selenium 4.x 호환
            try:
                from webdriver_manager.chrome import ChromeDriverManager

                # Selenium 4.x 방식으로 Service 객체 사용
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                self.logger.info("webdriver-manager로 Chrome 드라이버 설정 완료")

            except ImportError:
                self.logger.warning("webdriver-manager가 설치되지 않음. 시스템 Chrome 드라이버 사용")
                # 시스템에 설치된 Chrome 드라이버 사용
                self.driver = webdriver.Chrome(options=options)

            # 브라우저 설정 최적화
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)

            # 자동화 탐지 스크립트 제거
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
            self.driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko']})")

            self.logger.info("Selenium Chrome 드라이버 설정 완료")

        except Exception as e:
            self.logger.error(f"Chrome 드라이버 설정 실패: {e}")
            self.logger.error("해결 방법들:")
            self.logger.error("1. pip install webdriver-manager")
            self.logger.error("2. Chrome 브라우저가 설치되어 있는지 확인")
            self.logger.error("3. Chrome 버전과 호환되는 chromedriver 설치")
            raise

    def start_requests(self):
        """시작 요청 생성 - Selenium 우선 사용"""
        # URL fragment 제거
        if '#' in self.start_url:
            self.start_url = self.start_url.split('#')[0]

        self.logger.info("Selenium을 사용하여 직접 크롤링을 시작합니다.")

        # Selenium으로 직접 크롤링 시작
        yield scrapy.Request(
            url="https://httpbin.org/delay/1",  # 더미 요청
            callback=self.start_selenium_crawling,
            dont_filter=True
        )

    def start_selenium_crawling(self, response):
        """Selenium을 사용한 직접 크롤링 - 개선된 버전"""
        try:
            # 먼저 상품 페이지에서 제품명 가져오기
            self.page_title = self.get_product_title_from_selenium()

            if not self.page_title or "실패" in self.page_title:
                self.logger.error(f"상품명을 가져올 수 없습니다: {self.page_title}")
                # 상품명을 못 가져와도 계속 진행
                self.page_title = f"상품_{self.product_code}"

            self.logger.info(f"사용할 상품명: {self.page_title}")

            # 먼저 리뷰 페이지 구조 확인을 위해 첫 페이지 테스트
            self.logger.info("리뷰 페이지 구조 분석을 시작합니다...")
            test_success = self.test_review_page_structure()

            if not test_success:
                self.logger.error("리뷰 페이지에 접근할 수 없거나 구조를 파악할 수 없습니다.")
                return

            # 페이지별로 크롤링 시작
            page = 1
            consecutive_empty_pages = 0
            max_empty_pages = 3
            total_reviews = 0

            while consecutive_empty_pages < max_empty_pages and page <= 100:
                self.logger.info(f"페이지 {page} 크롤링 중...")

                # 리뷰 페이지 URL 생성
                review_url = f"{self.base_review_url}?productId={self.product_code}&page={page}&size=5&sortBy=ORDER_SCORE_ASC&ratings=&q=&viRoleCode=2&ratingSummary=true"

                try:
                    # Selenium으로 페이지 접근
                    self.driver.get(review_url)

                    # 페이지 로딩 대기
                    loading_time = random.uniform(5, 8)
                    self.logger.info(f"페이지 로딩 대기: {loading_time:.1f}초")
                    time.sleep(loading_time)

                    # 현재 URL 확인
                    current_url = self.driver.current_url
                    self.logger.debug(f"현재 URL: {current_url}")

                    # 페이지 소스 가져오기
                    page_source = self.driver.page_source

                    # 차단 확인
                    if self.check_page_blocked(page_source, page):
                        consecutive_empty_pages += 1
                        page += 1
                        continue

                    # BeautifulSoup으로 파싱
                    soup = bs(page_source, "html.parser")

                    # 다양한 리뷰 선택자 시도
                    articles = self.find_review_articles(soup, page)

                    if not articles:
                        consecutive_empty_pages += 1
                        self.logger.warning(
                            f"페이지 {page}에서 리뷰를 찾을 수 없습니다. ({consecutive_empty_pages}/{max_empty_pages})")

                        # 디버깅: 페이지 소스 일부 저장
                        if page <= 3:  # 처음 3페이지만
                            self.save_debug_info(page_source, page)

                        page += 1
                        continue

                    consecutive_empty_pages = 0
                    self.logger.info(f"페이지 {page}에서 {len(articles)}개 리뷰 발견")

                    # 각 리뷰 파싱 및 반환
                    page_reviews = 0
                    for article in articles:
                        item = self.parse_single_review_selenium(article)
                        if item:
                            yield item
                            page_reviews += 1
                            total_reviews += 1

                    self.logger.info(f"페이지 {page}에서 {page_reviews}개 리뷰 성공적으로 파싱")
                    page += 1

                    # 페이지 간 랜덤 딜레이
                    if page <= 101:  # 다음 페이지가 있을 때만
                        delay = random.uniform(3, 6)
                        self.logger.info(f"다음 페이지까지 {delay:.1f}초 대기...")
                        time.sleep(delay)

                except Exception as e:
                    self.logger.error(f"페이지 {page} 크롤링 중 오류: {e}")
                    consecutive_empty_pages += 1
                    page += 1

                    # 긴 대기 후 재시도
                    retry_delay = random.uniform(10, 15)
                    self.logger.info(f"오류 복구를 위해 {retry_delay:.1f}초 대기...")
                    time.sleep(retry_delay)

            self.logger.info(f"크롤링 완료 - 총 {total_reviews}개 리뷰, {page - 1}페이지 처리")

        except Exception as e:
            self.logger.error(f"Selenium 크롤링 중 심각한 오류 발생: {e}")
            import traceback
            self.logger.error(f"스택 트레이스: {traceback.format_exc()}")
        finally:
            # 안전한 드라이버 종료
            self.safe_driver_quit()

    def test_review_page_structure(self):
        """리뷰 페이지 구조 테스트"""
        try:
            test_url = f"{self.base_review_url}?productId={self.product_code}&page=1&size=5"
            self.logger.info(f"리뷰 페이지 테스트: {test_url}")

            self.driver.get(test_url)
            time.sleep(5)

            page_source = self.driver.page_source
            soup = bs(page_source, "html.parser")

            # 다양한 패턴으로 리뷰 찾기
            selectors_to_test = [
                "article.sdp-review__article__list",
                "article[class*='review']",
                "div[class*='review-item']",
                "div[class*='review-list']",
                ".review-item",
                "[data-review-id]",
                "div[class*='sdp-review']"
            ]

            for selector in selectors_to_test:
                elements = soup.select(selector)
                if elements:
                    self.logger.info(f"리뷰 선택자 '{selector}' 발견: {len(elements)}개 요소")
                    return True
                else:
                    self.logger.debug(f"리뷰 선택자 '{selector}' 실패")

            # HTML 구조 디버깅
            self.logger.warning("표준 리뷰 선택자로 요소를 찾을 수 없음")
            self.logger.info("페이지 내 주요 요소들:")

            # 주요 클래스나 ID 확인
            important_elements = soup.find_all(['div', 'article', 'section'], limit=20)
            for elem in important_elements:
                if elem.get('class') or elem.get('id'):
                    self.logger.info(f"발견된 요소: {elem.name}, class: {elem.get('class')}, id: {elem.get('id')}")

            return False

        except Exception as e:
            self.logger.error(f"리뷰 페이지 구조 테스트 실패: {e}")
            return False

    def find_review_articles(self, soup, page_num):
        """다양한 방법으로 리뷰 아티클 찾기"""
        # 기본 선택자들
        selectors = [
            "article.sdp-review__article__list",
            "article[class*='review']",
            "div[class*='review-item']",
            "div[class*='review-list']",
            ".review-item",
            "[data-review-id]",
            "div[class*='sdp-review'][class*='article']"
        ]

        for selector in selectors:
            articles = soup.select(selector)
            if articles:
                self.logger.debug(f"페이지 {page_num}: 선택자 '{selector}'로 {len(articles)}개 리뷰 발견")
                return articles

        # 텍스트 패턴으로 찾기 (최후 수단)
        self.logger.debug(f"페이지 {page_num}: 선택자 실패, 텍스트 패턴 검색 시도")

        # 리뷰 관련 키워드가 있는 요소들 찾기
        all_divs = soup.find_all('div', limit=100)
        review_like_elements = []

        for div in all_divs:
            text = div.get_text().strip()
            if any(keyword in text for keyword in ['평점', '별점', '리뷰', '구매', '만족', '추천']):
                if len(text) > 50:  # 충분한 텍스트가 있는 경우
                    review_like_elements.append(div)

        if review_like_elements:
            self.logger.info(f"페이지 {page_num}: 텍스트 패턴으로 {len(review_like_elements)}개 리뷰 후보 발견")
            return review_like_elements[:5]  # 최대 5개만 반환

        return []

    def check_page_blocked(self, page_source, page_num):
        """페이지 차단 여부 확인"""
        blocked_indicators = [
            "403", "Forbidden", "차단", "접근이 제한",
            "사이트에 연결할 수 없", "Connection refused",
            "Access Denied", "페이지를 찾을 수 없"
        ]

        for indicator in blocked_indicators:
            if indicator in page_source:
                self.logger.warning(f"페이지 {page_num} 차단 감지: '{indicator}'")

                # 차단 감지 시 긴 대기
                wait_time = random.uniform(60, 120)
                self.logger.info(f"차단 해제를 위해 {wait_time / 60:.1f}분 대기...")
                time.sleep(wait_time)
                return True

        return False

    def save_debug_info(self, page_source, page_num):
        """디버깅 정보 저장"""
        try:
            # HTML 저장
            with open(f"debug_review_page_{page_num}.html", "w", encoding="utf-8") as f:
                f.write(page_source)

            # 스크린샷 저장
            self.driver.save_screenshot(f"debug_review_page_{page_num}.png")

            self.logger.info(f"디버깅 파일 저장: debug_review_page_{page_num}.html, debug_review_page_{page_num}.png")

        except Exception as e:
            self.logger.warning(f"디버깅 파일 저장 실패: {e}")

    def safe_driver_quit(self):
        """안전한 드라이버 종료"""
        try:
            if hasattr(self, 'driver') and self.driver:
                self.logger.info("Selenium 드라이버 종료 중...")
                self.driver.quit()
                self.logger.info("Selenium 드라이버 종료 완료")
        except Exception as e:
            self.logger.warning(f"드라이버 종료 중 오류 (무시됨): {e}")
            try:
                # 강제 종료 시도
                self.driver.close()
            except:
                pass

    def parse_single_review_selenium(self, article):
        """Selenium에서 가져온 HTML로 단일 리뷰 파싱"""
        try:
            item = CoupangReviewItem()

            # 리뷰 날짜
            review_date_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__reg-date"
            )
            item['review_date'] = review_date_elem.text.strip() if review_date_elem else "-"

            # 구매자 이름
            user_name_elem = article.select_one(
                "span.sdp-review__article__list__info__user__name"
            )
            item['user_name'] = user_name_elem.text.strip() if user_name_elem else "-"

            # 평점
            rating_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__star-orange"
            )
            if rating_elem and rating_elem.get("data-rating"):
                try:
                    item['rating'] = int(rating_elem.get("data-rating"))
                except (ValueError, TypeError):
                    item['rating'] = 0
            else:
                item['rating'] = 0

            # 구매자 상품명
            prod_name_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__name"
            )
            item['prod_name'] = prod_name_elem.text.strip() if prod_name_elem else "-"

            # 헤드라인
            headline_elem = article.select_one(
                "div.sdp-review__article__list__headline"
            )
            item['headline'] = headline_elem.text.strip() if headline_elem else "등록된 헤드라인이 없습니다"

            # 리뷰 내용
            review_content_elem = article.select_one(
                "div.sdp-review__article__list__review__content.js_reviewArticleContent"
            )
            if review_content_elem:
                item['review_content'] = re.sub("[\n\t]", "", review_content_elem.text.strip())
            else:
                # 백업 선택자 시도
                review_content_elem = article.select_one(
                    "div.sdp-review__article__list__review > div"
                )
                if review_content_elem:
                    item['review_content'] = re.sub("[\n\t]", "", review_content_elem.text.strip())
                else:
                    item['review_content'] = "등록된 리뷰내용이 없습니다"

            # 맛 만족도
            answer_elem = article.select_one(
                "span.sdp-review__article__list__survey__row__answer"
            )
            item['answer'] = answer_elem.text.strip() if answer_elem else "맛 평가 없음"

            # 도움이 된 사람 수
            helpful_count_elem = article.select_one("span.js_reviewArticleHelpfulCount")
            item['helpful_count'] = helpful_count_elem.text.strip() if helpful_count_elem else "0"

            # 판매자 정보
            seller_name_elem = article.select_one(
                "div.sdp-review__article__list__info__product-info__seller_name"
            )
            if seller_name_elem:
                item['seller_name'] = seller_name_elem.text.replace("판매자: ", "").strip()
            else:
                item['seller_name'] = "-"

            # 리뷰 이미지 개수
            review_images = article.select("div.sdp-review__article__list__attachment__list img")
            item['image_count'] = len(review_images)

            # 상품명
            item['title'] = self.page_title or "상품명 미확인"

            return item

        except Exception as e:
            self.logger.error(f"리뷰 파싱 중 오류 발생: {e}")
            return None

    def get_product_title_from_selenium(self):
        """Selenium을 사용하여 상품명 추출 - 개선된 버전"""
        try:
            url = f"https://www.coupang.com/vp/products/{self.product_code}"
            self.logger.info(f"상품 페이지 접속 중: {url}")

            # 페이지 로드
            self.driver.get(url)

            # 더 긴 페이지 로딩 대기
            self.logger.info("페이지 로딩 대기 중...")
            try:
                WebDriverWait(self.driver, 60).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.TAG_NAME, "h1")),
                        EC.presence_of_element_located((By.CLASS_NAME, "prod-buy-header__title")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='title']"))
                    )
                )
                self.logger.info("페이지 요소 감지됨")
            except Exception as e:
                self.logger.warning(f"페이지 로딩 대기 중 예외: {e}")

            # 추가 대기 (JavaScript 실행 완료)
            wait_time = random.uniform(5, 8)
            self.logger.info(f"JavaScript 실행 완료 대기: {wait_time:.1f}초")
            time.sleep(wait_time)

            # 현재 URL 확인
            current_url = self.driver.current_url
            self.logger.info(f"현재 URL: {current_url}")

            # 페이지 제목 확인
            page_title = self.driver.title
            self.logger.info(f"페이지 제목: {page_title}")

            # 페이지 소스 가져오기
            page_source = self.driver.page_source

            # 디버깅: HTML 일부 저장
            debug_html = page_source[:2000]
            self.logger.debug(f"HTML 시작 부분: {debug_html}")

            # 403 에러나 차단 페이지 체크
            blocked_keywords = ["403", "Forbidden", "차단", "접근이 제한", "사이트에 연결할 수 없"]
            for keyword in blocked_keywords:
                if keyword in page_source:
                    self.logger.warning(f"페이지 차단 감지: '{keyword}' 키워드 발견")
                    # 스크린샷 저장 (디버깅용)
                    try:
                        self.driver.save_screenshot("debug_blocked_page.png")
                        self.logger.info("차단된 페이지 스크린샷 저장: debug_blocked_page.png")
                    except:
                        pass
                    return f"페이지 차단됨 ({keyword})"

            soup = bs(page_source, "html.parser")

            # 다양한 상품명 선택자 시도
            title_selectors = [
                "h1.prod-buy-header__title",
                ".prod-buy-header__title",
                "h1[class*='title']",
                ".product-title",
                "h1",
                "[data-testid='product-title']",
                ".prod-title",
                ".product-name",
                "h2[class*='title']"
            ]

            for i, selector in enumerate(title_selectors):
                self.logger.info(f"선택자 {i + 1} 시도: {selector}")
                title_elem = soup.select_one(selector)
                if title_elem and title_elem.text.strip():
                    title = title_elem.text.strip()
                    self.logger.info(f"상품명 발견 (선택자 {i + 1}): {title}")
                    return title
                else:
                    self.logger.debug(f"선택자 {i + 1} 실패: 요소 없음")

            # 텍스트에서 상품명 패턴 찾기 (최후 수단)
            self.logger.info("선택자로 찾기 실패, 텍스트 패턴 검색 시도...")

            # 페이지 텍스트에서 가능한 상품명 찾기
            text_lines = page_source.split('\n')
            for line in text_lines[:50]:  # 처음 50줄만 확인
                line = line.strip()
                if len(line) > 10 and len(line) < 200:  # 적당한 길이의 텍스트
                    # 상품명 같은 패턴 찾기
                    if any(keyword in line for keyword in ['[', ']', '/', '(', ')', '-']):
                        clean_line = bs(line, "html.parser").get_text().strip()
                        if clean_line and len(clean_line) > 10:
                            self.logger.info(f"텍스트 패턴으로 상품명 후보 발견: {clean_line}")
                            return clean_line

            # 디버깅을 위한 HTML 전체 저장
            try:
                with open("debug_page_source.html", "w", encoding="utf-8") as f:
                    f.write(page_source)
                self.logger.info("디버깅용 HTML 저장: debug_page_source.html")
            except:
                pass

            # 스크린샷 저장
            try:
                self.driver.save_screenshot("debug_product_page.png")
                self.logger.info("디버깅용 스크린샷 저장: debug_product_page.png")
            except:
                pass

            self.logger.warning("모든 방법으로 상품명을 찾을 수 없습니다.")
            return "상품명 추출 실패"

        except Exception as e:
            self.logger.error(f"get_product_title_from_selenium 에러: {e}")
            try:
                self.driver.save_screenshot("debug_error.png")
                self.logger.info("에러 시 스크린샷 저장: debug_error.png")
            except:
                pass
            return f"상품명 추출 실패 (예외: {str(e)[:50]})"

    @staticmethod
    def get_product_code(url):
        """URL에서 상품 코드 추출"""
        return url.split("products/")[-1].split("?")[0]

    def closed(self, reason):
        """스파이더 종료 시 드라이버 정리"""
        self.safe_driver_quit()
        self.logger.info(f"스파이더 종료: {reason}")
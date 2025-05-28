import scrapy
import re
import time
import random
from bs4 import BeautifulSoup as bs
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from coupang_reviews_scrapy.items import CoupangReviewItem


class CoupangReviewSpider(scrapy.Spider):
    name = 'coupang_review'
    allowed_domains = ['coupang.com']

    custom_settings = {
        'COOKIES_ENABLED': True,
        'DOWNLOAD_DELAY': 2,
        'RANDOMIZE_DOWNLOAD_DELAY': 0.5,
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

        # 헤더 설정
        self.headers = {
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "ko,en;q=0.9,en-US;q=0.8",
            "cookie": "_fbp=fb.1.1709172148924.2042270649; gd1=Y; delivery_toggle=false;",
            "priority": "u=1, i",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

    def setup_selenium(self):
        """Selenium WebDriver 설정"""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("lang=ko_KR")
        options.add_argument("--log-level=3")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        self.driver = webdriver.Chrome(options=options)

    def start_requests(self):
        """시작 요청 생성"""
        # URL fragment 제거
        if '#' in self.start_url:
            self.start_url = self.start_url.split('#')[0]

        self.headers["Referer"] = self.start_url

        # 첫 번째 페이지 요청
        yield self.make_review_request(page=1)

    def make_review_request(self, page):
        """리뷰 페이지 요청 생성"""
        params = {
            "productId": self.product_code,
            "page": page,
            "size": 5,
            "sortBy": "ORDER_SCORE_ASC",
            "ratings": "",
            "q": "",
            "viRoleCode": 2,
            "ratingSummary": True,
        }

        return scrapy.Request(
            url=self.base_review_url,
            callback=self.parse_reviews,
            headers=self.headers,
            meta={
                'page': page,
                'params': params,
                'dont_cache': True,
            },
            dont_filter=True,
        )

    def parse_reviews(self, response):
        """리뷰 페이지 파싱"""
        current_page = response.meta['page']
        self.logger.info(f"페이지 {current_page} 파싱 중...")

        soup = bs(response.text, "html.parser")

        # 상품명 설정 (첫 페이지에서만)
        if self.page_title is None:
            self.page_title = self.get_product_title_from_selenium()

        # 리뷰 아티클 선택
        articles = soup.select("article.sdp-review__article__list")

        if not articles:
            self.logger.warning(f"페이지 {current_page}에서 리뷰를 찾을 수 없습니다.")
            return

        self.logger.info(f"페이지 {current_page}에서 {len(articles)}개 리뷰 발견")

        # 각 리뷰 파싱
        for article in articles:
            item = self.parse_single_review(article)
            if item:
                yield item

        # 다음 페이지 요청
        if len(articles) > 0:  # 리뷰가 있으면 다음 페이지 시도
            next_page = current_page + 1
            if next_page <= 1000:  # 최대 1000페이지까지
                # 페이지 간 딜레이
                delay = random.uniform(1.0, 3.0)
                time.sleep(delay)
                yield self.make_review_request(page=next_page)

    def parse_single_review(self, article):
        """단일 리뷰 파싱"""
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
        """Selenium을 사용하여 상품명 추출"""
        try:
            url = f"https://www.coupang.com/vp/products/{self.product_code}"
            self.logger.info(f"상품 페이지 접속 중: {url}")

            self.driver.get(url)

            # 페이지 로딩 대기
            WebDriverWait(self.driver, 30).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # 추가 대기
            time.sleep(random.uniform(2.0, 5.0))

            page_source = self.driver.page_source
            soup = bs(page_source, "html.parser")

            # 상품명 추출
            title_selectors = [
                "h1.prod-buy-header__title",
                ".prod-buy-header__title",
                "h1[class*='title']",
                ".product-title",
                "h1"
            ]

            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem and title_elem.text.strip():
                    title = title_elem.text.strip()
                    self.logger.info(f"상품명 발견: {title}")
                    return title

            self.logger.warning("상품명을 찾을 수 없습니다.")
            return "상품명 추출 실패"

        except Exception as e:
            self.logger.error(f"get_product_title_from_selenium 에러: {e}")
            return "상품명 추출 실패"

    @staticmethod
    def get_product_code(url):
        """URL에서 상품 코드 추출"""
        return url.split("products/")[-1].split("?")[0]

    def closed(self, reason):
        """스파이더 종료 시 드라이버 정리"""
        if hasattr(self, 'driver'):
            self.driver.quit()
        self.logger.info(f"스파이더 종료: {reason}")
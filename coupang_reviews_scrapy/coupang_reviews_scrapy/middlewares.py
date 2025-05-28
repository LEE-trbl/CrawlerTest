import time
import random
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
from scrapy.http import HtmlResponse
from fake_useragent import UserAgent


class CoupangAntiDetectionMiddleware:
    """
    403 에러 방지를 위한 봇 탐지 회피 미들웨어
    """

    def __init__(self):
        self.ua = UserAgent()
        self.session_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

    def process_request(self, request, spider):
        # 랜덤 User-Agent 설정
        try:
            request.headers['User-Agent'] = self.ua.random
        except:
            request.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'

        # 현실적인 헤더 추가
        for key, value in self.session_headers.items():
            request.headers[key] = value

        # Referer 설정 (쿠팡 메인 페이지에서 온 것처럼)
        if 'coupang.com' in request.url:
            request.headers['Referer'] = 'https://www.coupang.com/'

        return None

    def process_response(self, request, response, spider):
        # 403 에러 처리
        if response.status == 403:
            spider.logger.warning(f"403 Forbidden 에러 발생: {request.url}")
            spider.logger.info("더 긴 딜레이 후 재시도 예정...")

            # 긴 딜레이 추가
            delay = random.uniform(5, 10)
            time.sleep(delay)

            # 새로운 요청 생성 (헤더 변경)
            new_request = request.copy()
            new_request.headers['User-Agent'] = self.ua.random
            new_request.dont_filter = True

            return new_request

        return response


class CoupangTimeoutMiddleware(RetryMiddleware):
    """
    기존 코드의 타임아웃 처리 로직을 Scrapy 미들웨어로 구현
    """

    def __init__(self, settings):
        super().__init__(settings)
        self.consecutive_timeouts = 0
        self.consecutive_403s = 0  # 403 에러 카운터 추가
        self.max_consecutive_timeouts = 5
        self.max_consecutive_403s = 3  # 연속 403 에러 최대 횟수
        self.long_wait_min = 300  # 5분
        self.long_wait_max = 360  # 6분

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def process_response(self, request, response, spider):
        if response.status == 403:
            self.consecutive_403s += 1
            spider.logger.warning(f"403 에러 발생 (연속 {self.consecutive_403s}회)")

            if self.consecutive_403s >= self.max_consecutive_403s:
                self._handle_consecutive_403s(spider)

            reason = f"403 Forbidden (attempt {self.consecutive_403s})"
            return self._retry(request, reason, spider) or response

        elif response.status in self.retry_http_codes:
            reason = response_status_message(response.status)
            return self._retry(request, reason, spider) or response

        # 성공적인 응답이면 카운터 리셋
        self.consecutive_timeouts = 0
        self.consecutive_403s = 0
        return response

    def process_exception(self, request, exception, spider):
        if self._is_timeout_error(exception):
            self.consecutive_timeouts += 1
            spider.logger.warning(f"타임아웃 발생 (연속 {self.consecutive_timeouts}회): {exception}")

            if self.consecutive_timeouts >= self.max_consecutive_timeouts:
                self._handle_consecutive_timeouts(spider)

            return self._retry(request, str(exception), spider)

        return super().process_exception(request, exception, spider)

    def _is_timeout_error(self, exception):
        """타임아웃 관련 예외인지 확인"""
        timeout_keywords = ['timeout', 'timed out', 'connection timeout']
        exception_str = str(exception).lower()
        return any(keyword in exception_str for keyword in timeout_keywords)

    def _handle_consecutive_timeouts(self, spider):
        """연속 타임아웃 처리"""
        wait_time = random.uniform(self.long_wait_min, self.long_wait_max)
        wait_minutes = wait_time / 60
        spider.logger.warning(f"연속 {self.consecutive_timeouts}회 타임아웃 발생!")
        spider.logger.info(f"서버 안정화를 위해 {wait_minutes:.1f}분 대기합니다...")

        time.sleep(wait_time)
        spider.logger.info("대기 완료! 크롤링을 재개합니다.")
        self.consecutive_timeouts = 0

    def _handle_consecutive_403s(self, spider):
        """연속 403 에러 처리"""
        wait_time = random.uniform(600, 900)  # 10-15분 대기
        wait_minutes = wait_time / 60
        spider.logger.warning(f"연속 {self.consecutive_403s}회 403 에러 발생!")
        spider.logger.info(f"봇 탐지 해제를 위해 {wait_minutes:.1f}분 대기합니다...")

        time.sleep(wait_time)
        spider.logger.info("대기 완료! 크롤링을 재개합니다.")
        self.consecutive_403s = 0
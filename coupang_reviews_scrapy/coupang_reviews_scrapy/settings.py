BOT_NAME = 'coupang_reviews_scrapy'

SPIDER_MODULES = ['coupang_reviews_scrapy.spiders']
NEWSPIDER_MODULE = 'coupang_reviews_scrapy.spiders'

# 로봇 배제 표준 무시 (403 에러 방지)
ROBOTSTXT_OBEY = False

# 동시 요청 수 제한 (서버 부하 방지)
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1

# 다운로드 딜레이 설정 (더 길게 설정하여 탐지 방지)
DOWNLOAD_DELAY = 3
RANDOMIZE_DOWNLOAD_DELAY = 1.0

# 더 현실적인 User-Agent 설정
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

# 쿠키 활성화
COOKIES_ENABLED = True

# 타임아웃 설정 (더 길게)
DOWNLOAD_TIMEOUT = 30

# 재시도 설정
RETRY_ENABLED = True
RETRY_TIMES = 3  # 403 에러 시 재시도 횟수 줄임
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429, 403]  # 403 추가

# 로그 레벨
LOG_LEVEL = 'INFO'

# HTTP 에러 처리 (403 에러도 처리하도록)
HTTPERROR_ALLOWED_CODES = [403]

# 아이템 파이프라인 활성화
ITEM_PIPELINES = {
    'coupang_reviews_scrapy.pipelines.CoupangReviewsPipeline': 300,
}

# 미들웨어 활성화 (순서 변경 - 커스텀 미들웨어를 더 앞에)
DOWNLOADER_MIDDLEWARES = {
    'coupang_reviews_scrapy.middlewares.CoupangAntiDetectionMiddleware': 350,
    'coupang_reviews_scrapy.middlewares.CoupangTimeoutMiddleware': 543,
}

# AutoThrottle 설정 (더 보수적으로)
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5

# 더 현실적인 헤더 설정
DEFAULT_REQUEST_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
}

# REQUEST_FINGERPRINTER_IMPLEMENTATION 설정 (경고 제거)
REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
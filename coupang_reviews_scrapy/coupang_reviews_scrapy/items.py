import scrapy


class CoupangReviewItem(scrapy.Item):
    title = scrapy.Field()           # 상품명
    prod_name = scrapy.Field()       # 구매상품명
    review_date = scrapy.Field()     # 작성일자
    user_name = scrapy.Field()       # 구매자명
    rating = scrapy.Field()          # 평점
    headline = scrapy.Field()        # 헤드라인
    review_content = scrapy.Field()  # 리뷰내용
    answer = scrapy.Field()          # 맛만족도
    helpful_count = scrapy.Field()   # 도움수
    seller_name = scrapy.Field()     # 판매자
    image_count = scrapy.Field()     # 이미지수
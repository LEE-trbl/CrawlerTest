import json
from typing import List, Dict, Any
import pandas as pd


def remove_duplicate_product_ids(data: List[Dict[str, Any]], keep_strategy: str = 'first') -> List[Dict[str, Any]]:
    """
    product_id가 중복된 항목들을 제거하는 함수

    Args:
        data: 제품 데이터 리스트
        keep_strategy: 중복 제거 전략
            - 'first': 첫 번째 항목만 유지
            - 'last': 마지막 항목만 유지
            - 'highest_rating': 평점이 높은 항목 유지
            - 'most_reviews': 리뷰가 많은 항목 유지
            - 'lowest_price': 가격이 낮은 항목 유지

    Returns:
        중복이 제거된 제품 데이터 리스트
    """

    if keep_strategy == 'first':
        # 첫 번째 항목만 유지
        seen_ids = set()
        unique_products = []

        for product in data:
            product_id = product.get('product_id')
            if product_id not in seen_ids:
                seen_ids.add(product_id)
                unique_products.append(product)

        return unique_products

    elif keep_strategy == 'last':
        # 마지막 항목만 유지 (역순으로 처리 후 다시 역순)
        seen_ids = set()
        unique_products = []

        for product in reversed(data):
            product_id = product.get('product_id')
            if product_id not in seen_ids:
                seen_ids.add(product_id)
                unique_products.append(product)

        return list(reversed(unique_products))

    else:
        # 특정 기준으로 최적 항목 선택
        product_groups = {}

        # product_id별로 그룹화
        for product in data:
            product_id = product.get('product_id')
            if product_id not in product_groups:
                product_groups[product_id] = []
            product_groups[product_id].append(product)

        unique_products = []

        for product_id, products in product_groups.items():
            if len(products) == 1:
                unique_products.append(products[0])
            else:
                # 전략에 따라 최적 항목 선택
                best_product = select_best_product(products, keep_strategy)
                unique_products.append(best_product)

        return unique_products


def select_best_product(products: List[Dict[str, Any]], strategy: str) -> Dict[str, Any]:
    """여러 제품 중에서 전략에 따라 최적의 제품을 선택"""

    if strategy == 'highest_rating':
        # 평점이 높은 순으로 정렬
        def get_rating(product):
            try:
                return float(product.get('rating', '0'))
            except (ValueError, TypeError):
                return 0

        return max(products, key=get_rating)

    elif strategy == 'most_reviews':
        # 리뷰 수가 많은 순으로 정렬
        def get_review_count(product):
            try:
                review_count = product.get('review_count', '0')
                # 숫자에서 쉼표 제거
                return int(review_count.replace(',', ''))
            except (ValueError, TypeError, AttributeError):
                return 0

        return max(products, key=get_review_count)

    elif strategy == 'lowest_price':
        # 가격이 낮은 순으로 정렬
        def get_price(product):
            try:
                price = product.get('price', '0')
                # 쉼표 제거하고 숫자만 추출
                return int(price.replace(',', ''))
            except (ValueError, TypeError, AttributeError):
                return float('inf')  # 가격 정보가 없으면 무한대로 설정

        return min(products, key=get_price)

    else:
        # 기본값: 첫 번째 항목 반환
        return products[0]


def analyze_duplicates(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """중복 데이터 분석"""

    product_counts = {}
    for product in data:
        product_id = product.get('product_id')
        product_counts[product_id] = product_counts.get(product_id, 0) + 1

    duplicates = {pid: count for pid, count in product_counts.items() if count > 1}

    return {
        'total_products': len(data),
        'unique_product_ids': len(product_counts),
        'duplicate_product_ids': len(duplicates),
        'duplicates_detail': duplicates
    }


# 사용 예시
def main():
    # JSON 파일 읽기
    with open('홈플래닛_products_20250603_180442.json', 'r', encoding='utf-8') as f:
        products_data = json.load(f)

    print("=== 중복 분석 ===")
    duplicate_analysis = analyze_duplicates(products_data)
    print(f"전체 제품 수: {duplicate_analysis['total_products']}")
    print(f"고유 product_id 수: {duplicate_analysis['unique_product_ids']}")
    print(f"중복된 product_id 수: {duplicate_analysis['duplicate_product_ids']}")

    if duplicate_analysis['duplicates_detail']:
        print("\n중복된 product_id들:")
        for pid, count in duplicate_analysis['duplicates_detail'].items():
            print(f"  {pid}: {count}개")

    # 여러 전략으로 중복 제거
    strategies = ['first', 'last', 'highest_rating', 'most_reviews', 'lowest_price']

    for strategy in strategies:
        print(f"\n=== {strategy} 전략으로 중복 제거 ===")

        cleaned_data = remove_duplicate_product_ids(products_data, strategy)
        print(f"중복 제거 후 제품 수: {len(cleaned_data)}")

        # 결과 저장
        output_filename = f'homeplanet_products_dedup_{strategy}.json'
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

        print(f"저장 완료: {output_filename}")


# pandas를 사용한 간단한 방법
def remove_duplicates_with_pandas(data: List[Dict[str, Any]], keep: str = 'first') -> List[Dict[str, Any]]:
    """pandas를 사용한 간단한 중복 제거"""

    df = pd.DataFrame(data)

    # product_id 기준으로 중복 제거
    df_unique = df.drop_duplicates(subset=['product_id'], keep=keep)

    return df_unique.to_dict('records')


if __name__ == "__main__":
    main()
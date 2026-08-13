"""오프라인 인덱싱에서 공통으로 사용하는 예외."""


class IndexingContractError(ValueError):
    """전처리 결과가 builder의 필수 입력 계약을 만족하지 않을 때 발생한다."""

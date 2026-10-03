class DataPipelineError(Exception):
    """Data Pipeline에서 예상 가능한 오류의 기본 예외."""


class PaperFetchError(DataPipelineError):
    """Hugging Face Papers API 조회에 실패했다."""


class PreprocessingError(DataPipelineError):
    """논문 본문을 Markdown으로 확보하지 못했다.

    PDF 다운로드나 변환에 실패했거나 변환 결과가 너무 짧은 경우다.
    """

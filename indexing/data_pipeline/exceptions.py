class DataPipelineError(Exception):
    """Data Pipeline에서 예상 가능한 오류의 기본 예외."""


class PaperFetchError(DataPipelineError):
    """Hugging Face Papers API 조회에 실패했다."""


class PreprocessingError(DataPipelineError):
    """논문 본문을 Markdown으로 확보하지 못했다.

    HF Markdown 응답이 유효하지 않고 PDF 변환까지 실패한 경우다.
    """

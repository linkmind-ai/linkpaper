"""프론트엔드 논문 목록·뷰어가 사용하는 응답 모델."""

from pydantic import BaseModel, Field


class Paper(BaseModel):
    id: str  # Hugging Face Papers ID. 채팅의 paperId로 그대로 사용한다.
    title: str
    authors: str  # 화면 표시용 저자 문자열
    year: int | None = None
    categories: list[str] = Field(default_factory=list)  # HF AI 키워드 상위 항목
    summary: str = ""
    pdfUrl: str | None = None  # arXiv 논문일 때만 채운다.
    arxivUrl: str | None = None  # arXiv 논문일 때만 채운다.

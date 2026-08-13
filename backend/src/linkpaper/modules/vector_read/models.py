"""Qdrant read 모델.

필드명은 indexing/vector_builder가 적재하는 payload 계약과 일치시킨다.
"""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class VectorSearchScope(StrEnum):
    SELECTED_PAPER = "selected_paper"  # 사용자가 선택한 논문 안에서만 검색
    GLOBAL_CORPUS = "global_corpus"  # 사전에 구축한 글로벌 논문 전체에서 검색


class VectorSearchRequest(BaseModel):
    query_vector: list[float] = Field(min_length=1)  # 사용자 질문의 임베딩 벡터
    scope: VectorSearchScope  # 선택 논문 또는 글로벌 검색 범위
    paper_id: str | None = None  # 선택 논문 검색에 사용할 전역 논문 ID
    limit: int = Field(default=8, ge=1, le=100)  # 반환할 최대 검색 결과 수
    score_threshold: float | None = Field(
        default=None, ge=0.0, le=1.0
    )  # 이 점수보다 유사도가 낮은 결과는 제외

    @model_validator(mode="after")
    def validate_scope(self) -> "VectorSearchRequest":
        # 선택 논문 검색은 paper_id가 있어야 Qdrant 범위를 안전하게 제한할 수 있다.
        if self.scope is VectorSearchScope.SELECTED_PAPER and not self.paper_id:
            raise ValueError("selected_paper 범위에는 paper_id가 필요합니다")
        if self.scope is VectorSearchScope.GLOBAL_CORPUS and self.paper_id:
            raise ValueError("global_corpus 범위에는 paper_id를 지정하지 않습니다")
        return self


class VectorChunkPayload(BaseModel):
    chunk_id: str  # Neo4j Chunk와 연결하는 전역 청크 ID
    paper_id: str  # 청크가 속한 논문의 전역 ID
    chunk_index: int  # 논문 안에서 청크가 등장하는 순서
    text: str  # 검색 결과와 답변 근거로 사용할 청크 원문
    section: str | None = None  # 청크가 속한 섹션 제목
    char_count: int  # 청크 원문의 문자 수
    content_hash: str  # 청크 내용 변경 여부를 판단하는 해시
    title: str  # 결과 표시와 문맥 제공에 사용할 논문 제목
    published_at: str | None = None  # 논문의 최초 공개 시각
    source_version: str  # 본문 확보 방식(hf-markdown 또는 PDF 파서)
    in_global_corpus: bool  # 글로벌 확장 검색 대상 포함 여부
    embedding_provider: str  # 임베딩 제공자(예: openai)
    embedding_model: str  # 적재할 때 사용한 임베딩 모델명
    embedding_dimension: int  # 저장된 임베딩 벡터 차원
    embedding_version: str  # 인덱스와 질의 모델을 맞추는 임베딩 버전


class VectorSearchHit(BaseModel):
    point_id: str  # Qdrant 내부 point UUID
    score: float  # Cosine 유사도 검색 점수
    payload: VectorChunkPayload  # 검색된 청크의 메타데이터와 원문

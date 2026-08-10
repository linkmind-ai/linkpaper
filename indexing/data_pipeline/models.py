"""Data Pipeline과 Graph Builder 사이의 데이터 계약.

docs/data-architecture/data-retrieval-architecture.md 4장의 NormalizedPaper /
NormalizedChunk를 따르되, 이 파이프라인이 실제로 채울 수 있는 필드만 둔다.
채우지 못하는 값을 `None`으로 남겨두면 Graph Builder가 있는 값과 없는 값을
구분하지 못하기 때문이다.

청크 길이는 토크나이저에 종속적인 `tokenCount` 대신 현재 문자 기반 청킹과
일치하는 `char_count`로 기록한다.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 본문을 어떤 경로로 확보했는지. 재처리 판단과 품질 추적에 쓴다.
MarkdownSource = Literal["hf-markdown", "pdf-pymupdf4llm"]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PaperMetadata(BaseModel):
    """논문 한 편의 메타데이터.

    Client가 만드는 초기 메타데이터와 Metadata Curator가 완성한 최종
    메타데이터가 같은 모델을 공유한다. 둘의 차이는 큐레이션 필드가 채워졌는지
    뿐이라 모델을 나누면 필드만 중복된다.

    `paper_id`는 Hugging Face Papers의 논문 ID(= arXiv base ID)를 그대로 쓴다.
    Preprocessor의 Markdown 주소와 Chunk ID가 이 값을 그대로 사용한다.
    """

    model_config = ConfigDict(extra="ignore")

    paper_id: str
    arxiv_id: str | None = None
    title: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    published_at: datetime | None = None
    source_url: str = ""
    pdf_url: str | None = None

    # 아래는 Metadata Curator가 채우는 값이다.
    references: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    source_version: MarkdownSource | None = None


class PaperMarkdown(BaseModel):
    """Preprocessor가 확보한 논문 본문 Markdown."""

    model_config = ConfigDict(extra="ignore")

    paper_id: str
    text: str
    source: MarkdownSource

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)


class PaperChunk(BaseModel):
    """검색과 근거 추적의 단위.

    `paper_id`와 `section`으로 이 청크가 어느 논문의 어느 섹션에서 나왔는지
    항상 식별할 수 있다.
    """

    model_config = ConfigDict(extra="ignore")

    # neo4j-schema.md 7.2: <paperId>:chunk:<chunkIndex>:<contentHash-prefix>
    chunk_id: str
    paper_id: str
    chunk_index: int
    text: str
    section: str
    section_index: int
    # 참고문헌 섹션은 여러 청크로 나뉠 수 있다. 임베딩 대상에서 제외할지는
    # Graph Builder가 이 플래그로 판단한다.
    is_references: bool = False
    char_count: int = 0
    content_hash: str = ""


class ChunkedPaper(BaseModel):
    """Chunker의 출력.

    청크 목록과, Metadata Curator에 넘길 참고문헌 섹션 원문을 함께 낸다.
    """

    model_config = ConfigDict(extra="ignore")

    chunks: list[PaperChunk] = Field(default_factory=list)
    references_text: str = ""


class ProcessedPaper(BaseModel):
    """논문 한 편의 처리 결과. Graph Builder의 입력이다."""

    model_config = ConfigDict(extra="ignore")

    metadata: PaperMetadata
    chunks: list[PaperChunk] = Field(default_factory=list)


class PaperOutcome(BaseModel):
    """배치에서 논문 한 편이 어떻게 끝났는지.

    한 편이 실패해도 배치를 멈추지 않으므로 성공과 실패를 같은 형태로 모은다.
    """

    model_config = ConfigDict(extra="ignore")

    paper_id: str
    paper: ProcessedPaper | None = None
    stage: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.paper is not None


class PipelineRun(BaseModel):
    """배치 실행 한 번의 결과. Job이 로그와 재시도 판단에 쓴다."""

    model_config = ConfigDict(extra="ignore")

    mode: Literal["base", "daily"]
    window: str
    started_at: datetime
    finished_at: datetime
    outcomes: list[PaperOutcome] = Field(default_factory=list)

    @property
    def papers(self) -> list[ProcessedPaper]:
        return [outcome.paper for outcome in self.outcomes if outcome.paper is not None]

    @property
    def failures(self) -> list[PaperOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.ok]

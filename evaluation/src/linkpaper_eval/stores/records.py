"""저장소 사이를 오가는 공통 레코드.

Qdrant payload, Neo4j `:Chunk` 노드, `fixtures/*.jsonl` 코퍼스가 모두 이
형태로 정규화된다. 세 곳의 필드 이름이 조금씩 다르더라도 변환은 이 파일
안에서만 일어나므로, 나머지 코드는 하나의 형태만 알면 된다.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_ARXIV_PREFIXED = re.compile(r"^(arxiv|hf|ref):", re.IGNORECASE)


def normalize_paper_id(raw: str, default_prefix: str = "arxiv") -> str:
    """neo4j-schema.md 7.1의 Paper ID 형식으로 맞춘다.

    이미 접두사가 있으면 그대로 두고, 없으면 붙인다. 외부 벤치마크는
    `1706.03762`처럼 접두사 없는 ID를 쓰는 경우가 많아서 필요하다.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    if _ARXIV_PREFIXED.match(value):
        return value
    return f"{default_prefix}:{value}"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_chunk_id(paper_id: str, chunk_index: int, text: str) -> str:
    """neo4j-schema.md 7.2: `<paperId>:chunk:<chunkIndex>:<contentHash-prefix>`.

    인덱싱 파이프라인과 같은 규칙을 쓰므로, 벤치마크 코퍼스로 만든 청크
    ID와 실제 서비스 청크 ID의 형식이 어긋나지 않는다.
    """
    return f"{paper_id}:chunk:{chunk_index}:{content_hash(text)[:8]}"


class ChunkRecord(BaseModel):
    """검색과 근거 추적의 단위."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    paper_id: str
    text: str
    section: str | None = None
    chunk_index: int | None = None
    title: str | None = None
    is_references: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        paper_id: str,
        chunk_index: int,
        text: str,
        section: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChunkRecord:
        normalized = normalize_paper_id(paper_id)
        return cls(
            chunk_id=make_chunk_id(normalized, chunk_index, text),
            paper_id=normalized,
            chunk_index=chunk_index,
            text=text,
            section=section,
            title=title,
            metadata=metadata or {},
        )

    def to_corpus_row(self) -> dict[str, Any]:
        """`fixtures/mock_corpus.jsonl`과 호환되는 한 줄.

        기존 BM25 베이스라인 타깃이 그대로 읽을 수 있어야 벤치마크
        코퍼스와 오프라인 베이스라인을 같은 지표로 비교할 수 있다.
        """
        row: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "paper_id": self.paper_id,
            "text": self.text,
        }
        if self.section:
            row["section"] = self.section
        if self.chunk_index is not None:
            row["chunk_index"] = self.chunk_index
        if self.title:
            row["title"] = self.title
        return row

    def to_payload(self) -> dict[str, Any]:
        """Qdrant payload / Neo4j 노드 속성 공통 형태."""
        return {
            "chunk_id": self.chunk_id,
            "paper_id": self.paper_id,
            "text": self.text,
            "section": self.section,
            "chunk_index": self.chunk_index,
            "title": self.title,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ChunkRecord:
        """snake_case와 camelCase를 모두 받는다.

        Qdrant payload는 적재 주체에 따라 표기가 갈린다. 인덱싱 팀이
        camelCase로 넣어도 평가가 깨지지 않게 두 표기를 모두 읽는다.
        """

        def pick(*names: str) -> Any:
            for name in names:
                if payload.get(name) not in (None, ""):
                    return payload[name]
            return None

        chunk_id = pick("chunk_id", "chunkId", "id") or ""
        paper_id = pick("paper_id", "paperId") or ""
        return cls(
            chunk_id=str(chunk_id),
            paper_id=str(paper_id),
            text=str(pick("text", "content", "page_content") or ""),
            section=pick("section", "sectionTitle"),
            chunk_index=pick("chunk_index", "chunkIndex"),
            title=pick("title", "paperTitle"),
            is_references=bool(pick("is_references", "isReferences") or False),
        )


class SearchHit(BaseModel):
    """벡터 검색 결과 하나."""

    model_config = ConfigDict(extra="ignore")

    chunk: ChunkRecord
    score: float
    rank: int | None = None

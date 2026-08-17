"""온라인 단일 논문 검색의 공통 모델."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    paper_id: str
    text: str
    score: float


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    paper_id: str
    text: str
    vector: list[float]

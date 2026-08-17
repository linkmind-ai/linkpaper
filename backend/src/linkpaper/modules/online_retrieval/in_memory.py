"""단일 논문을 위한 교체 가능한 인메모리 검색 구현."""

from __future__ import annotations

import hashlib
import math

from linkpaper.modules.online_retrieval.backend import EmbeddingClient
from linkpaper.modules.online_retrieval.models import IndexedChunk, RetrievedChunk


class InMemoryRetrievalBackend:
    def __init__(
        self,
        embedder: EmbeddingClient,
        *,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> None:
        if chunk_size <= chunk_overlap:
            raise ValueError("chunk_size는 chunk_overlap보다 커야 합니다")
        self.embedder = embedder
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._paper_id: str | None = None
        self._chunks: list[IndexedChunk] = []

    @property
    def paper_id(self) -> str | None:
        return self._paper_id

    async def index(self, paper_id: str, content: str) -> None:
        texts = self._split(content)
        vectors = await self.embedder.embed_texts(texts)
        if len(texts) != len(vectors):
            raise ValueError("청크 수와 임베딩 수가 다릅니다")

        chunks = [
            IndexedChunk(
                chunk_id=self._chunk_id(paper_id, index, text),
                paper_id=paper_id,
                text=text,
                vector=vector,
            )
            for index, (text, vector) in enumerate(zip(texts, vectors))
        ]
        self._paper_id = paper_id
        self._chunks = chunks

    async def search(
        self,
        paper_id: str,
        query: str,
        limit: int,
    ) -> list[RetrievedChunk]:
        if paper_id != self._paper_id or not self._chunks:
            raise ValueError(f"{paper_id}: 메모리 인덱스가 없습니다")
        if limit < 1:
            raise ValueError("limit은 1 이상이어야 합니다")

        query_vectors = await self.embedder.embed_texts([query])
        query_vector = query_vectors[0]
        ranked = sorted(
            self._chunks,
            key=lambda chunk: self._cosine(query_vector, chunk.vector),
            reverse=True,
        )[:limit]
        return [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                paper_id=chunk.paper_id,
                text=chunk.text,
                score=self._cosine(query_vector, chunk.vector),
            )
            for chunk in ranked
        ]

    async def reset(self) -> None:
        self._paper_id = None
        self._chunks = []

    def _split(self, content: str) -> list[str]:
        normalized = content.strip()
        if not normalized:
            raise ValueError("인덱싱할 본문이 비어 있습니다")

        step = self.chunk_size - self.chunk_overlap
        return [
            normalized[start : start + self.chunk_size]
            for start in range(0, len(normalized), step)
            if normalized[start : start + self.chunk_size].strip()
        ]

    @staticmethod
    def _chunk_id(paper_id: str, index: int, text: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        return f"{paper_id}:online:{index}:{digest}"

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise ValueError("비교할 임베딩 차원이 다릅니다")
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        dot_product = sum(a * b for a, b in zip(left, right))
        return dot_product / (left_norm * right_norm)

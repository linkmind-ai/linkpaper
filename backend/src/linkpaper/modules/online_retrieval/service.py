"""본문 확보와 검색 backend의 생명주기를 조율한다."""

import asyncio
from typing import Protocol

from linkpaper.modules.online_retrieval.backend import RetrievalBackend
from linkpaper.modules.online_retrieval.models import RetrievedChunk


class PaperContentSource(Protocol):
    async def fetch(self, paper_id: str) -> str: ...


class OnlineRetrievalService:
    def __init__(
        self,
        backend: RetrievalBackend,
        source: PaperContentSource,
        *,
        default_limit: int = 5,
    ) -> None:
        self.backend = backend
        self.source = source
        self.default_limit = default_limit
        self._lock = asyncio.Lock()

    async def search(
        self,
        paper_id: str,
        query: str,
        *,
        limit: int | None = None,
    ) -> list[RetrievedChunk]:
        # 인덱스 교체와 검색을 한 단위로 묶어 다른 논문의 요청과 섞이지 않게 한다.
        async with self._lock:
            await self._ensure_indexed(paper_id)
            return await self.backend.search(
                paper_id,
                query,
                limit=limit or self.default_limit,
            )

    async def _ensure_indexed(self, paper_id: str) -> None:
        if self.backend.paper_id == paper_id:
            return

        content = await self.source.fetch(paper_id)
        await self.backend.index(paper_id, content)

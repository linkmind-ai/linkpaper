"""검색 구현체가 따라야 하는 최소 인터페이스."""

from collections.abc import Sequence
from typing import Protocol

from linkpaper.modules.online_retrieval.models import RetrievedChunk


class RetrievalBackend(Protocol):
    @property
    def paper_id(self) -> str | None: ...

    async def index(self, paper_id: str, content: str) -> None: ...

    async def search(
        self, paper_id: str, query: str, limit: int
    ) -> list[RetrievedChunk]: ...

    async def reset(self) -> None: ...


class EmbeddingClient(Protocol):
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...

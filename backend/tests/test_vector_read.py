from types import SimpleNamespace

import pytest
from linkpaper.core.config import Settings
from linkpaper.core.exceptions import StoreSchemaMismatchError
from linkpaper.modules.vector_read import (
    VectorReadService,
    VectorSearchRequest,
    VectorSearchScope,
)
from pydantic import ValidationError


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        qdrant_collection="chunks-test",
        linkpaper_embedding_dimensions=3,
        linkpaper_embedding_version="embedding-v1",
    )


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "chunk_id": "arxiv:1:chunk:0:abc",
        "paper_id": "arxiv:1",
        "chunk_index": 0,
        "text": "chunk text",
        "section": "Introduction",
        "char_count": 10,
        "content_hash": "abc",
        "title": "Paper",
        "published_at": "2026-07-01T00:00:00+00:00",
        "source_version": "hf-markdown",
        "in_global_corpus": False,
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-large",
        "embedding_dimension": 3,
        "embedding_version": "embedding-v1",
    }
    payload.update(overrides)
    return payload


class FakeQdrantClient:
    def __init__(self) -> None:
        self.query_kwargs: dict[str, object] = {}
        self.closed = False

    async def query_points(self, **kwargs: object) -> SimpleNamespace:
        self.query_kwargs = kwargs
        return SimpleNamespace(
            points=[
                SimpleNamespace(id="point-1", score=0.91, payload=_payload()),
            ]
        )

    async def scroll(self, **_: object) -> tuple[list[object], None]:
        return [SimpleNamespace(id="point-1")], None

    async def get_collection(self, _: str) -> SimpleNamespace:
        vectors = SimpleNamespace(size=3, distance="Cosine")
        return SimpleNamespace(
            config=SimpleNamespace(params=SimpleNamespace(vectors=vectors))
        )

    async def close(self) -> None:
        self.closed = True


def test_selected_scope_requires_paper_id() -> None:
    with pytest.raises(ValidationError):
        VectorSearchRequest(
            query_vector=[0.1, 0.2, 0.3],
            scope=VectorSearchScope.SELECTED_PAPER,
        )


def test_selected_paper_search_uses_paper_filter() -> None:
    async def run() -> None:
        client = FakeQdrantClient()
        service = VectorReadService(settings=_settings(), client=client)

        hits = await service.search(
            VectorSearchRequest(
                query_vector=[0.1, 0.2, 0.3],
                scope=VectorSearchScope.SELECTED_PAPER,
                paper_id="arxiv:1",
            )
        )

        assert hits[0].payload.chunk_id == "arxiv:1:chunk:0:abc"
        assert client.query_kwargs["query_filter"] == {
            "must": [{"key": "paper_id", "match": {"value": "arxiv:1"}}]
        }

    import asyncio

    asyncio.run(run())


def test_global_search_uses_global_corpus_filter() -> None:
    async def run() -> None:
        client = FakeQdrantClient()
        service = VectorReadService(settings=_settings(), client=client)

        await service.search(
            VectorSearchRequest(
                query_vector=[0.1, 0.2, 0.3],
                scope=VectorSearchScope.GLOBAL_CORPUS,
            )
        )

        assert client.query_kwargs["query_filter"] == {
            "must": [
                {"key": "in_global_corpus", "match": {"value": True}},
            ]
        }

    import asyncio

    asyncio.run(run())


def test_query_dimension_must_match_index() -> None:
    async def run() -> None:
        service = VectorReadService(settings=_settings(), client=FakeQdrantClient())

        with pytest.raises(StoreSchemaMismatchError, match="질의 벡터 차원 불일치"):
            await service.search(
                VectorSearchRequest(
                    query_vector=[0.1, 0.2],
                    scope=VectorSearchScope.GLOBAL_CORPUS,
                )
            )

    import asyncio

    asyncio.run(run())


def test_qdrant_connection_schema_and_paper_existence() -> None:
    async def run() -> None:
        client = FakeQdrantClient()
        service = VectorReadService(settings=_settings(), client=client)

        await service.verify_schema()
        assert await service.has_paper("arxiv:1") is True
        await service.close()
        assert client.closed is True

    import asyncio

    asyncio.run(run())

from collections.abc import AsyncIterator
from typing import Any, Self

from linkpaper.core.config import Settings
from linkpaper.modules.knowledge_graph import KnowledgeGraphService


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        neo4j_database="neo4j-test",
        linkpaper_schema_version="v1",
    )


def _paper(paper_id: str = "arxiv:1") -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "arxiv_id": paper_id.removeprefix("arxiv:"),
        "title": "Paper",
        "abstract": "Abstract",
        "published_at": "2026-07-01",
        "source_version": "hf-markdown",
        "source_url": "https://huggingface.co/papers/1",
        "pdf_url": "https://arxiv.org/pdf/1",
        "processing_status": "completed",
        "content_hash": "paper-hash",
        "schema_version": "v1",
        "in_global_corpus": True,
    }


class FakeRecord(dict[str, Any]):
    def data(self) -> dict[str, Any]:
        return dict(self)


class FakeResult:
    def __init__(self, records: list[FakeRecord]) -> None:
        self.records = records

    async def single(self) -> FakeRecord | None:
        return self.records[0] if self.records else None

    def __aiter__(self) -> AsyncIterator[FakeRecord]:
        async def iterate() -> AsyncIterator[FakeRecord]:
            for record in self.records:
                yield record

        return iterate()


class FakeSession:
    def __init__(self, results: list[list[FakeRecord]]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def run(self, query: str, **parameters: object) -> FakeResult:
        self.calls.append({"query": query, "parameters": parameters})
        return FakeResult(self.results.pop(0))


class FakeNeo4jDriver:
    def __init__(self, results: list[list[FakeRecord]]) -> None:
        self.fake_session = FakeSession(results)
        self.database: str | None = None
        self.connected = False
        self.closed = False

    def session(self, *, database: str) -> FakeSession:
        self.database = database
        return self.fake_session

    async def verify_connectivity(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True


def test_get_paper_graph_maps_schema_and_sorts_children() -> None:
    async def run() -> None:
        record = FakeRecord(
            paper=_paper(),
            authors=[
                {
                    "author_id": "author:2",
                    "name": "B",
                    "normalized_name": "b",
                    "author_order": 1,
                },
                {
                    "author_id": "author:1",
                    "name": "A",
                    "normalized_name": "a",
                    "author_order": 0,
                },
            ],
            chunks=[
                {
                    "chunk_id": "chunk:1",
                    "paper_id": "arxiv:1",
                    "chunk_index": 1,
                    "text": "second",
                    "section": None,
                    "char_count": 6,
                    "content_hash": "b",
                    "in_global_corpus": True,
                },
                {
                    "chunk_id": "chunk:0",
                    "paper_id": "arxiv:1",
                    "chunk_index": 0,
                    "text": "first",
                    "section": "Intro",
                    "char_count": 5,
                    "content_hash": "a",
                    "in_global_corpus": True,
                },
            ],
            citations=[
                {
                    "source_paper_id": "arxiv:1",
                    "target_paper_id": "arxiv:2",
                }
            ],
        )
        driver = FakeNeo4jDriver([[record]])
        service = KnowledgeGraphService(settings=_settings(), driver=driver)

        graph = await service.get_paper_graph("arxiv:1", global_only=True)

        assert graph is not None
        assert graph.paper.paper_id == "arxiv:1"
        assert [author.name for author in graph.authors] == ["A", "B"]
        assert [chunk.chunk_index for chunk in graph.chunks] == [0, 1]
        assert graph.citations[0].target_paper_id == "arxiv:2"
        assert driver.database == "neo4j-test"

    import asyncio

    asyncio.run(run())


def test_expand_citations_uses_chunk_join_key() -> None:
    async def run() -> None:
        record = FakeRecord(
            source_chunk_id="chunk:0",
            source_paper_id="arxiv:1",
            relationship_type="CITES",
            related_paper=_paper("arxiv:2"),
        )
        driver = FakeNeo4jDriver([[record]])
        service = KnowledgeGraphService(settings=_settings(), driver=driver)

        result = await service.expand_citations(
            ["chunk:0", "chunk:0"],
            global_only=True,
        )

        assert result[0].related_paper.paper_id == "arxiv:2"
        parameters = driver.fake_session.calls[0]["parameters"]
        assert parameters == {
            "chunk_ids": ["chunk:0"],
            "global_only": True,
            "limit": 50,
        }

    import asyncio

    asyncio.run(run())


def test_neo4j_connection_and_paper_existence() -> None:
    async def run() -> None:
        driver = FakeNeo4jDriver([[FakeRecord(exists=True)]])
        service = KnowledgeGraphService(settings=_settings(), driver=driver)

        await service.verify_connection()
        assert driver.connected is True
        assert await service.has_paper("arxiv:1") is True
        await service.close()
        assert driver.closed is True

    import asyncio

    asyncio.run(run())

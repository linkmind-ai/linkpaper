import asyncio

from linkpaper.modules.online_retrieval import (
    InMemoryRetrievalBackend,
    OnlineRetrievalService,
)


class FakeEmbedder:
    async def embed_texts(self, texts):
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text):
        normalized = text.casefold()
        return [
            float("attention" in normalized),
            float("graph" in normalized),
        ]


class FakeSource:
    def __init__(self):
        self.calls = []

    async def fetch(self, paper_id):
        self.calls.append(paper_id)
        return "attention model\n\n" + "graph retrieval"


def test_in_memory_backend_returns_most_similar_chunk() -> None:
    backend = InMemoryRetrievalBackend(
        embedder=FakeEmbedder(),
        chunk_size=18,
        chunk_overlap=0,
    )

    async def run():
        await backend.index("paper-1", "attention model   graph retrieval")
        return await backend.search("paper-1", "attention", limit=1)

    results = asyncio.run(run())

    assert len(results) == 1
    assert "attention" in results[0].text
    assert results[0].score == 1.0


def test_service_reuses_index_for_same_paper() -> None:
    source = FakeSource()
    backend = InMemoryRetrievalBackend(
        embedder=FakeEmbedder(),
        chunk_size=100,
        chunk_overlap=0,
    )
    service = OnlineRetrievalService(backend=backend, source=source)

    async def run():
        await service.search("paper-1", "attention")
        await service.search("paper-1", "graph")

    asyncio.run(run())

    assert source.calls == ["paper-1"]

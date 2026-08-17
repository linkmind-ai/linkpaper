import asyncio

from linkpaper.modules.retrieval import PaperChunk, RetrievalService


def test_searches_only_selected_paper() -> None:
    service = RetrievalService()
    service.add_chunks(
        [
            PaperChunk(
                id="c-001",
                paper_id="p-001",
                content="Transformer uses self attention",
            ),
            PaperChunk(
                id="c-002",
                paper_id="p-002",
                content="Another paper uses self attention",
            ),
        ]
    )

    results = asyncio.run(
        service.search_paper("p-001", "self attention")
    )

    assert len(results) == 1
    assert results[0].chunk.id == "c-001"

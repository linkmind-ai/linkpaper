from __future__ import annotations

from datetime import UTC, datetime

from data_pipeline.models import PaperChunk, PaperMetadata, ProcessedPaper
from graph_builder.builder import Neo4jGraphBuilder, prepare_graph_payload


def sample_paper() -> ProcessedPaper:
    return ProcessedPaper(
        metadata=PaperMetadata(
            paper_id="1706.03762",
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            abstract="Transformer paper",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            published_at=datetime(2017, 6, 12, tzinfo=UTC),
            source_url="https://huggingface.co/papers/1706.03762",
            pdf_url="https://arxiv.org/pdf/1706.03762",
            references=["1607.06450"],
            content_hash="paper-hash",
            source_version="hf-markdown",
        ),
        chunks=[
            PaperChunk(
                chunk_id=f"1706.03762:chunk:{index}:{digest[:8]}",
                paper_id="1706.03762",
                chunk_index=index,
                text=text,
                section="Introduction",
                section_index=0,
                char_count=len(text),
                content_hash=digest,
            )
            for index, (text, digest) in enumerate(
                [("first", "a" * 64), ("second", "b" * 64)]
            )
        ],
    )


class FakeResult:
    def consume(self) -> None:
        return None


class FakeTransaction:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return FakeResult()


class FakeSession:
    def __init__(self, tx: FakeTransaction) -> None:
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def execute_write(self, callback, *args):
        return callback(self.tx, *args)

    def run(self, query: str):
        return self.tx.run(query)


class FakeDriver:
    def __init__(self) -> None:
        self.tx = FakeTransaction()
        self.database = None

    def session(self, *, database: str):
        self.database = database
        return FakeSession(self.tx)

    def close(self) -> None:
        return None


def test_prepare_graph_payload_builds_structure_and_citation_stub() -> None:
    payload = prepare_graph_payload(sample_paper(), "v1")

    assert payload["paper"]["paperId"] == "arxiv:1706.03762"
    assert payload["paper"]["publishedAt"] == "2017-06-12"
    assert payload["chunkIds"] == [
        "arxiv:1706.03762:chunk:0:aaaaaaaa",
        "arxiv:1706.03762:chunk:1:bbbbbbbb",
    ]
    assert payload["pairs"] == [
        {"left": payload["chunkIds"][0], "right": payload["chunkIds"][1]}
    ]
    assert payload["references"][0]["paperId"] == "arxiv:1607.06450"
    assert payload["authors"][0]["authorOrder"] == 0


def test_upsert_writes_one_transaction_and_global_labels() -> None:
    driver = FakeDriver()
    builder = Neo4jGraphBuilder(driver=driver)

    result = builder.upsert(sample_paper(), in_global_corpus=True)

    assert result.paper_id == "arxiv:1706.03762"
    assert result.chunks == 2
    assert driver.database == "neo4j"
    queries = "\n".join(query for query, _ in driver.tx.calls)
    assert "SET p:GlobalPaper" in queries
    assert "SET c:GlobalChunk" in queries
    assert "DETACH DELETE old" in queries
    assert "MERGE (p)-[:CITES]->(cited)" in queries


def test_ensure_schema_is_idempotent_statements() -> None:
    driver = FakeDriver()
    builder = Neo4jGraphBuilder(driver=driver)

    builder.ensure_schema()

    assert driver.tx.calls
    assert all("IF NOT EXISTS" in query for query, _ in driver.tx.calls)

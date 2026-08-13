"""로컬 Docker 저장소에 대한 opt-in smoke test.

RUN_STORE_INTEGRATION=1일 때만 실행하며 테스트 전용 Paper와 Qdrant collection은
성공 여부와 관계없이 정리한다.
"""

from __future__ import annotations

import os

import pytest

from data_pipeline.models import PaperChunk, PaperMetadata, ProcessedPaper
from graph_builder import Neo4jGraphBuilder
from indexing_common import BuilderSettings
from vector_builder import HashEmbedder, QdrantVectorBuilder

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_STORE_INTEGRATION") != "1",
        reason="RUN_STORE_INTEGRATION=1일 때만 실제 저장소에 연결합니다",
    ),
]

_PAPER_ID = "hf:linkpaper-builder-smoke-20260812"
_REFERENCE_ID = "arxiv:2601.99999"
_COLLECTION = "linkpaper_builder_smoke_v1"


def _paper() -> ProcessedPaper:
    return ProcessedPaper(
        metadata=PaperMetadata(
            paper_id=_PAPER_ID,
            title="LinkPaper Builder Smoke Test",
            authors=["Smoke Test Author"],
            references=[_REFERENCE_ID],
            content_hash="paper-smoke-hash",
            source_version="hf-markdown",
        ),
        chunks=[
            PaperChunk(
                chunk_id=f"{_PAPER_ID}:chunk:0:aaaaaaaa",
                paper_id=_PAPER_ID,
                chunk_index=0,
                text="Neo4j is written before Qdrant.",
                section="Smoke Test",
                section_index=0,
                char_count=32,
                content_hash="a" * 64,
            )
        ],
    )


def test_real_neo4j_and_qdrant_upsert_is_idempotent() -> None:
    settings = BuilderSettings(
        neo4j_uri="bolt://localhost:7687",
        qdrant_url="http://localhost:6333",
        qdrant_collection=_COLLECTION,
        embedding_dimensions=32,
    )
    graph = Neo4jGraphBuilder(settings)
    vector = QdrantVectorBuilder(
        settings,
        embedder=HashEmbedder(dimensions=32),
    )
    graph_written = False
    try:
        graph.ensure_schema()
        # 같은 입력을 두 번 적재해도 노드와 point 수가 늘지 않아야 한다.
        graph.upsert(_paper(), in_global_corpus=True)
        graph_written = True
        vector.upsert(_paper(), in_global_corpus=True)
        graph.upsert(_paper(), in_global_corpus=True)
        vector.upsert(_paper(), in_global_corpus=True)

        with graph.driver.session(database=settings.neo4j_database) as session:
            record = session.run(
                """
                MATCH (p:Paper {paperId: $paperId})-[:HAS_CHUNK]->(c:Chunk)
                OPTIONAL MATCH (p)-[:CITES]->(cited:Paper)
                RETURN count(DISTINCT c) AS chunks,
                       count(DISTINCT cited) AS citations,
                       p:GlobalPaper AS globalPaper,
                       all(chunk IN collect(c) WHERE chunk:GlobalChunk) AS globalChunks
                """,
                paperId=_PAPER_ID,
            ).single(strict=True)
        assert record["chunks"] == 1
        assert record["citations"] == 1
        assert record["globalPaper"] is True
        assert record["globalChunks"] is True
        assert vector.client.count(_COLLECTION, exact=True).count == 1
    finally:
        if graph_written:
            with graph.driver.session(database=settings.neo4j_database) as session:
                # 테스트 논문이 만든 author·chunk·citation stub까지 함께 정리한다.
                session.run(
                    """
                    MATCH (p:Paper {paperId: $paperId})
                    OPTIONAL MATCH (p)-[:AUTHORED_BY]->(a:Author)
                    OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c:Chunk)
                    DETACH DELETE p, a, c
                    """,
                    paperId=_PAPER_ID,
                ).consume()
                session.run(
                    "MATCH (p:Paper {paperId: $referenceId}) DETACH DELETE p",
                    referenceId=_REFERENCE_ID,
                ).consume()
        if vector._client is not None and vector.client.collection_exists(_COLLECTION):
            vector.client.delete_collection(_COLLECTION)
        vector.close()
        graph.close()

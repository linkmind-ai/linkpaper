from __future__ import annotations

import math
import uuid

import pytest
from qdrant_client import QdrantClient

from data_pipeline.models import PaperChunk, PaperMetadata, ProcessedPaper
from indexing_common import BuilderSettings
from vector_builder.builder import (
    QdrantVectorBuilder,
    point_id_for,
    prepare_vector_points,
)
from vector_builder.embedding import HashEmbedder


def sample_paper() -> ProcessedPaper:
    return ProcessedPaper(
        metadata=PaperMetadata(
            paper_id="1706.03762",
            arxiv_id="1706.03762",
            title="Attention Is All You Need",
            content_hash="paper-hash",
            source_version="hf-markdown",
        ),
        chunks=[
            PaperChunk(
                chunk_id=f"1706.03762:chunk:{index}:{digest[:8]}",
                paper_id="1706.03762",
                chunk_index=index,
                text=text,
                section=section,
                section_index=index,
                is_references=is_references,
                char_count=len(text),
                content_hash=digest,
            )
            for index, (text, section, is_references, digest) in enumerate(
                [
                    ("transformer attention", "Introduction", False, "a" * 64),
                    ("reference entry", "References", True, "b" * 64),
                ]
            )
        ],
    )


def test_hash_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashEmbedder(dimensions=32)

    first, second = embedder.embed(["same text", "same text"])

    assert first == second
    assert math.isclose(sum(value * value for value in first), 1.0)


def test_point_id_follows_documented_uuid5_contract() -> None:
    chunk_id = "arxiv:1706.03762:chunk:0:aaaaaaaa"

    assert point_id_for(chunk_id) == str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"linkpaper:chunk:{chunk_id}")
    )


def test_prepare_points_excludes_reference_chunks_by_default() -> None:
    embedder = HashEmbedder(dimensions=32)

    paper_id, points, skipped = prepare_vector_points(
        sample_paper(),
        in_global_corpus=True,
        include_reference_chunks=False,
        embedder=embedder,
        embedding_version="v1",
    )

    assert paper_id == "arxiv:1706.03762"
    assert len(points) == 1
    assert skipped == 1
    assert points[0].payload["paper_id"] == paper_id
    assert points[0].payload["in_global_corpus"] is True
    assert points[0].payload["embedding_dimension"] == 32


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect")
def test_global_membership_is_not_removed_by_non_global_reprocessing() -> None:
    client = QdrantClient(location=":memory:")
    settings = BuilderSettings(
        qdrant_collection="global_membership_test",
        embedding_dimensions=32,
    )
    builder = QdrantVectorBuilder(
        settings,
        client=client,
        embedder=HashEmbedder(dimensions=32),
    )

    builder.upsert(sample_paper(), in_global_corpus=True)
    updated = sample_paper()
    updated.chunks[0].text = "updated transformer attention"
    updated.chunks[0].char_count = len(updated.chunks[0].text)
    updated.chunks[0].content_hash = "c" * 64
    builder.upsert(updated, in_global_corpus=False)

    records, _ = client.scroll(
        collection_name="global_membership_test",
        with_payload=True,
        with_vectors=False,
    )
    assert len(records) == 1
    assert records[0].payload["chunk_id"].endswith(":cccccccc")
    assert records[0].payload["in_global_corpus"] is True

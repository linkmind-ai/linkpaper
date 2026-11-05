"""Opt-in production-indexer -> real Neo4j -> benchmark source contract test.

Run LINKPAPER_TEST_DOCKER_NEO4J=1 pytest tests/test_ontology_integration.py.
Only a uniquely named disposable container is accessed; no configured store
URLs, host volumes, or existing Docker services are used.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
import uuid

import pytest

from linkpaper_eval.stores.config import Neo4jSettings, StoreSettings
from linkpaper_eval.stores.neo4j_store import Neo4jStore
from linkpaper_eval.testgen.graph import build_chunk_graph
from linkpaper_eval.testgen.sources import from_neo4j

pytestmark = pytest.mark.skipif(
    os.environ.get("LINKPAPER_TEST_DOCKER_NEO4J") != "1",
    reason="opt in with LINKPAPER_TEST_DOCKER_NEO4J=1 for an isolated Docker instance",
)


@pytest.fixture
def isolated_neo4j():
    neo4j = pytest.importorskip("neo4j")
    name = f"linkpaper-benchmark-test-{uuid.uuid4().hex}"
    image = os.environ.get("LINKPAPER_TEST_NEO4J_IMAGE", "neo4j:5.26")
    password = "linkpaper-isolated-test"
    container_id = None
    driver = None
    try:
        result = subprocess.run(
            [
                "docker", "run", "--detach", "--rm", "--name", name,
                "--publish", "127.0.0.1::7687",
                "--env", f"NEO4J_AUTH=neo4j/{password}",
                "--env", "NEO4J_server_memory_heap_initial__size=256m",
                "--env", "NEO4J_server_memory_heap_max__size=256m",
                "--env", "NEO4J_server_memory_pagecache_size=256m",
                image,
            ],
            text=True, capture_output=True, check=True, timeout=120,
        )
        container_id = result.stdout.strip()
        address = subprocess.run(
            ["docker", "port", container_id, "7687/tcp"],
            text=True, capture_output=True, check=True, timeout=10,
        ).stdout.strip()
        settings = Neo4jSettings(uri=f"bolt://{address}", password=password, timeout_s=2)
        driver = neo4j.GraphDatabase.driver(
            settings.uri, auth=(settings.username, settings.password), connection_timeout=2,
        )
        deadline = time.monotonic() + 75
        while True:
            try:
                driver.verify_connectivity()
                break
            except neo4j.exceptions.Neo4jError:
                if time.monotonic() >= deadline:
                    raise
            except neo4j.exceptions.DriverError:
                if time.monotonic() >= deadline:
                    raise
            time.sleep(1)
        yield settings, driver
    finally:
        if driver is not None:
            driver.close()
        if container_id:
            subprocess.run(
                ["docker", "rm", "--force", container_id],
                text=True, capture_output=True, check=False, timeout=30,
            )


def test_production_indexer_to_real_graph_sources(isolated_neo4j, monkeypatch):
    settings, driver = isolated_neo4j
    indexing_path = Path(__file__).resolve().parents[2] / "indexing"
    monkeypatch.syspath_prepend(str(indexing_path))
    pytest.importorskip("pydantic_settings")
    from data_pipeline.models import PaperChunk, PaperMetadata, ProcessedPaper, content_hash
    from graph_builder.builder import Neo4jGraphBuilder
    from indexing_common.config import BuilderSettings

    def paper(identifier, references=()):
        texts = [f"{identifier} proposes a retrieval method.", f"{identifier} evaluates retrieval on scientific papers."]
        return ProcessedPaper(
            metadata=PaperMetadata(
                paper_id=identifier, arxiv_id=identifier, title=f"Paper {identifier}",
                authors=["Test Author"], references=list(references),
                source_version="pdf-pymupdf4llm", content_hash=content_hash("\n".join(texts)),
            ),
            chunks=[
                PaperChunk(
                    chunk_id=f"temporary:{index}", paper_id=identifier,
                    chunk_index=index, text=text, section="Results", section_index=0,
                    section_path="3 Results > 3.1 Retrieval", char_count=len(text),
                    content_hash=content_hash(text),
                )
                for index, text in enumerate(texts)
            ],
        )

    builder_settings = BuilderSettings(
        _env_file=None, NEO4J_URI=settings.uri, NEO4J_USERNAME=settings.username,
        NEO4J_PASSWORD=settings.password, NEO4J_DATABASE=settings.database,
    )
    builder = Neo4jGraphBuilder(settings=builder_settings, driver=driver)
    builder.ensure_schema()
    first = paper("2601.00001", ["2601.00002", "2601.99999"])
    second = paper("2601.00002")
    builder.upsert(first, in_global_corpus=True)
    builder.upsert(second, in_global_corpus=True)
    builder.upsert(first, in_global_corpus=True)  # idempotent production re-index

    stores = StoreSettings(neo4j=settings)
    records = from_neo4j(stores, paper_ids=["arxiv:2601.00001"], expand_hops=1)
    assert len(records) == 4
    assert {record.paper_id for record in records} == {"arxiv:2601.00001", "arxiv:2601.00002"}
    assert all(record.chunk_id.startswith(record.paper_id + ":chunk:") for record in records)
    assert all(record.section_path == "3 Results > 3.1 Retrieval" for record in records)
    assert all(record.source_version == "pdf-pymupdf4llm" for record in records)
    assert all(record.schema_version == "v1" and record.in_global_corpus for record in records)
    assert all(record.title and record.content_hash for record in records)

    scoped = from_neo4j(stores, paper_ids=["arxiv:2601.00002"], limit=1)
    assert len(scoped) == 1 and scoped[0].paper_id == "arxiv:2601.00002"
    snapshot = build_chunk_graph(records, stores, use_graph=True, use_vector=False)
    assert snapshot.summary()["links_by_type"] == {"next": 2, "cites": 4}
    assert all(link.metadata["relation_type"] == "CITES" for link in snapshot.links if link.type == "cites")
    with Neo4jStore(settings) as store:
        assert store.fetch_chunks([records[0].chunk_id])[0] == records[0]
        assert len(store.chunks_for_papers(["arxiv:2601.00001"])) == 2
        stub = store.query("MATCH (p:Paper {paperId: 'arxiv:2601.99999'}) RETURN p.processingStatus AS status")
        assert stub == [{"status": "reference_only"}]

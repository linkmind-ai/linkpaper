"""Production ontology and source selection contracts for benchmark snapshots."""

from __future__ import annotations

import uuid

import pytest

from linkpaper_eval.stores.config import QdrantSettings
from linkpaper_eval.stores.neo4j_store import Neo4jStore
from linkpaper_eval.stores.qdrant_store import QdrantStore, point_id_for
from linkpaper_eval.stores.records import ChunkRecord
from linkpaper_eval.testgen import graph, sources


def chunk(chunk_id="c1", paper_id="arxiv:1", **kwargs):
    return ChunkRecord(chunk_id=chunk_id, paper_id=paper_id, text=f"Evidence {chunk_id}", **kwargs)


def test_provenance_survives_snapshot_and_payload_round_trips():
    payload = {
        "chunkId": "arxiv:1234.56789:chunk:3:abc12345",
        "paperId": "arxiv:1234.56789", "text": "Experimental evidence.",
        "chunkIndex": 3, "sectionPath": "3 Experiments > 3.1 Setup",
        "contentHash": "abc12345", "sourceVersion": "pdf-pymupdf4llm",
        "schemaVersion": "1", "inGlobalCorpus": False,
        "embedding_provider": "openai", "embedding_model": "production-embedding",
        "embedding_dimension": 768, "embedding_version": "2026-10",
        "published_at": "2026-10-01",
    }
    record = ChunkRecord.from_payload(payload)
    assert record.in_global_corpus is False
    assert record.section_path == "3 Experiments > 3.1 Setup"
    assert record.metadata["embedding_dimension"] == 768
    assert record.metadata["published_at"] == "2026-10-01"
    assert ChunkRecord.from_payload(record.to_corpus_row()) == record
    assert ChunkRecord.from_payload(record.to_payload()) == record
    assert record.chunk_id == payload["chunkId"]


def test_jsonl_filters_before_limit_and_orders_stored_ids(tmp_path):
    path = tmp_path / "corpus.jsonl"
    rows = [chunk("z", "other"), chunk("b", "selected"), chunk("a", "selected")]
    path.write_text("\n".join(item.model_dump_json() for item in rows))
    result = sources.load_chunks("jsonl", corpus=path, paper_ids=["selected"], limit=1)
    assert [item.chunk_id for item in result] == ["a"]
    assert sources.from_jsonl(path, paper_ids=[]) == []


def test_conflicting_source_records_are_rejected(tmp_path):
    path = tmp_path / "corpus.jsonl"
    path.write_text("\n".join(item.model_dump_json() for item in [chunk(), chunk(paper_id="other")]))
    with pytest.raises(ValueError, match="Conflicting"):
        sources.from_jsonl(path)


def test_qdrant_point_id_matches_production_indexer():
    identifier = "arxiv:1706.03762:chunk:12:9f83a2c1"
    assert point_id_for(identifier) == str(uuid.uuid5(uuid.NAMESPACE_URL, f"linkpaper:chunk:{identifier}"))
    assert QdrantSettings().collection == "linkpaper_chunks_v1"


def test_qdrant_scope_filtered_before_limit_and_metadata_retained():
    pytest.importorskip("qdrant_client")
    with QdrantStore(QdrantSettings(url=":memory:")) as store:
        store.ensure_collection(vector_size=2)
        records = [chunk("unrelated", "other"), chunk("selected", "wanted", metadata={"embedding_model": "fixture"})]
        store.upsert_chunks(records, [[1.0, 0.0], [0.0, 1.0]])
        result = list(store.iter_chunks(limit=1, batch_size=1, paper_ids=["wanted"]))
        assert [item.chunk_id for item in result] == ["selected"]
        assert result[0].metadata["embedding_model"] == "fixture"
        assert list(store.iter_chunks(paper_ids=[])) == []
        assert store.search([1.0, 0.0], chunk_ids=[]) == []
        scoped = store.search([1.0, 0.0], chunk_ids=["selected"], exclude_paper_ids=["other"])
        assert [hit.chunk.chunk_id for hit in scoped] == ["selected"]


def test_live_vectors_use_indexed_vectors_and_snapshot_scope(monkeypatch):
    pytest.importorskip("qdrant_client")
    store = QdrantStore(QdrantSettings(url=":memory:"))
    try:
        store.ensure_collection(vector_size=2)
        records = [chunk("a", "one"), chunk("b", "two"), chunk("outside", "three")]
        store.upsert_chunks(records, [[1.0, 0.0], [0.9, 0.1], [1.0, 0.0]])
        monkeypatch.setattr(QdrantStore, "__enter__", lambda self: store)
        monkeypatch.setattr(QdrantStore, "__exit__", lambda *args: None)
        monkeypatch.setattr(graph, "build_embedder", lambda *args: pytest.fail("Must use indexed vectors"))
        result = graph.vector_links_qdrant(records[:2], min_score=0.0, top_k=1)
        assert {(link.source, link.target) for link in result} == {("a", "b"), ("b", "a")}
        assert all(link.metadata["origin"] == "qdrant" for link in result)
    finally:
        store.close()


def test_explicit_live_store_errors_propagate(monkeypatch):
    def fail(*args, **kwargs):
        raise ConnectionError("database unavailable")

    monkeypatch.setattr(graph, "graph_links", fail)
    with pytest.raises(ConnectionError, match="database unavailable"):
        graph.build_chunk_graph([chunk()], use_graph=True, use_vector=False)
    monkeypatch.setattr(graph, "vector_links_qdrant", fail)
    with pytest.raises(ConnectionError, match="database unavailable"):
        graph.build_chunk_graph([chunk()], use_graph=False, vector_backend="qdrant")


def test_local_order_does_not_invent_next_chunk_across_gaps():
    records = [chunk("a", chunk_index=0), chunk("b", chunk_index=2), chunk("c", chunk_index=3)]
    links = graph.same_paper_links(records)
    assert [link.type for link in links] == ["same_paper", "next"]
    assert all(link.metadata["origin"] == "corpus_order" for link in links)


def test_live_graph_uses_only_returned_relations(monkeypatch):
    records = [chunk("a", chunk_index=0), chunk("b", chunk_index=1)]
    monkeypatch.setattr(Neo4jStore, "graph_edges", lambda *args: [])
    assert graph.graph_links(records) == []


def test_neo4j_projection_retains_real_schema_and_deterministic_edges(monkeypatch):
    queries = []

    def query(self, cypher, parameters=None):
        queries.append((cypher, parameters))
        if "SKIP" in cypher:
            assert "sectionPath" in cypher and "contentHash" in cypher
            assert "sourceVersion" in cypher and "schemaVersion" in cypher
            assert "p.title" in cypher and "GlobalChunk" in cypher
            return [{"chunk_id": "c1", "paper_id": "p1", "text": "evidence", "title": "Paper", "section_path": "Results > Evaluation"}]
        if "CITES" in cypher:
            assert "ORDER BY" in cypher
            return [{"source": "c1", "target": "c2", "source_paper": "p1", "target_paper": "p2", "relation_type": "CITES"}]
        return []

    monkeypatch.setattr(Neo4jStore, "query", query)
    with Neo4jStore() as store:
        result = list(store.iter_chunks(paper_ids=["p1"], limit=1))
        assert result[0].title == "Paper"
        assert result[0].section_path == "Results > Evaluation"
        edges = store.graph_edges(["c1", "c2"])
        assert edges[0]["relation_type"] == "CITES"
        assert edges[0]["type"] == "cites"
        assert edges[0]["source_paper"] == "p1"
    assert queries[0][1]["paper_ids"] == ["p1"]

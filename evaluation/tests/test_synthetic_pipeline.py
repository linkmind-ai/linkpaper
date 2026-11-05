"""Source provenance, safe export, and reusable generation artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from linkpaper_eval.cli import main
from linkpaper_eval.stores.records import ChunkRecord
from linkpaper_eval.testgen import export, pipeline, sources
from linkpaper_eval.testgen.graph import ChunkGraph

CORPUS = Path(__file__).resolve().parents[1] / "fixtures/mock_corpus.jsonl"


class Testset:
    __test__ = False

    def __init__(self, rows):
        self.rows = rows

    def to_list(self):
        return self.rows


def sample(**overrides):
    return {"user_input": "What does the source state?", "reference": "It states alpha.",
            "reference_contexts": ["Alpha is a finding."], **overrides}


def test_export_requires_complete_unambiguous_evidence():
    chunks = [ChunkRecord(chunk_id="a", paper_id="p", text="Alpha is a finding."),
              ChunkRecord(chunk_id="b", paper_id="q", text="Alpha is a finding.")]
    cases, report = export.testset_to_cases(Testset([
        sample(),  # Ambiguous text needs explicit source IDs.
        sample(reference_context_ids=["a"]),
        sample(reference_context_ids=["unknown"]),
        sample(reference_contexts=["Alpha is a finding.", "Invented context"],
               reference_context_ids=["a", "b"]),
        sample(reference=""),
        sample(reference_context_ids=["a"]),  # Identical question/evidence.
    ]), chunks)
    assert len(cases) == 1
    assert cases[0]["gold_chunk_ids"] == ["a"]
    assert cases[0]["reference_contexts"] == [chunks[0].text]
    assert report.dropped_no_gold == 2
    assert report.dropped_incomplete_evidence == 1
    assert report.dropped_missing_reference == 1
    assert report.dropped_duplicate == 1


def test_export_does_not_turn_similar_text_into_gold():
    chunk = ChunkRecord(chunk_id="a", paper_id="p", text="Alpha is a finding.")
    cases, _ = export.testset_to_cases(Testset([
        sample(reference_contexts=["Alpha is not a finding."])
    ]), [chunk])
    assert cases == []


def test_snapshot_regeneration_does_not_read_live_sources(tmp_path, monkeypatch):
    original = pipeline.run("jsonl", tmp_path / "first.jsonl", corpus=CORPUS, size=10, seed=7)
    manifest = json.loads(Path(original.manifest).read_text())
    assert manifest["case_count"] == 10
    assert set(manifest["artifacts"]) == {"cases", "corpus", "graph"}
    assert manifest["parameters"]["seed"] == 7
    assert len(manifest["artifacts"]["graph"]["sha256"]) == 64
    monkeypatch.setattr(sources, "load_chunks", lambda *a, **kw: pytest.fail("Live read"))
    monkeypatch.setattr(pipeline, "build_chunk_graph", lambda *a, **kw: pytest.fail("Graph rebuild"))
    repeat = pipeline.regenerate(Path(original.manifest), tmp_path / "repeat.jsonl")
    assert Path(repeat.output).read_bytes() == Path(original.output).read_bytes()
    repeated_manifest = json.loads(Path(repeat.manifest).read_text())
    assert repeated_manifest["parent_manifest_sha256"]
    assert repeated_manifest["source_mode"] == "snapshot"


def test_changed_snapshot_rejected_before_generation(tmp_path):
    result = pipeline.run("jsonl", tmp_path / "first.jsonl", corpus=CORPUS, size=2)
    (tmp_path / "first.graph.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        pipeline.regenerate(Path(result.manifest), tmp_path / "second.jsonl")
    assert not (tmp_path / "second.jsonl").exists()


def test_output_protected_and_failed_generation_preserves_bundle(tmp_path, monkeypatch):
    result = pipeline.run("jsonl", tmp_path / "first.jsonl", corpus=CORPUS, size=2)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(FileExistsError):
        pipeline.run("jsonl", Path(result.output), corpus=CORPUS, size=2)
    monkeypatch.setattr(pipeline.offline_engine, "generate_offline", lambda *a, **kw: [])
    with pytest.raises(ValueError, match="No valid generated"):
        pipeline.run("jsonl", Path(result.output), corpus=CORPUS, size=2, overwrite=True)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("kwargs", [{"size": 0}, {"limit": -1}, {"single_hop_ratio": 2},
                                   {"expand_hops": 4}, {"vector_backend": "typo"}])
def test_bad_options_fail_before_db_access(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(sources, "load_chunks", lambda *a, **kw: pytest.fail("Live read"))
    with pytest.raises(ValueError):
        pipeline.run("neo4j", tmp_path / "bad.jsonl", **kwargs)


def test_ragas_generation_reuses_saved_kg_and_parameters(tmp_path, monkeypatch):
    from linkpaper_eval.testgen import ragas_engine

    chunks = sources.from_jsonl(CORPUS, limit=2)
    snapshot = ChunkGraph(chunks=chunks)
    calls = []

    def generate(graph, **kwargs):
        calls.append(kwargs)
        kwargs["knowledge_graph_path"].write_text("saved transformed KG")
        return Testset([sample(reference=chunks[0].text,
                              reference_contexts=[chunks[0].text],
                              reference_context_ids=[chunks[0].chunk_id])])

    monkeypatch.setattr(ragas_engine, "generate", generate)
    kg = SimpleNamespace(nodes=[SimpleNamespace(properties={
        "document_metadata": {"chunk_id": chunk.chunk_id}, "page_content": chunk.text
    }) for chunk in chunks])
    monkeypatch.setattr(ragas_engine, "load_knowledge_graph", lambda path: kg)
    result = pipeline.run("neo4j", tmp_path / "first.jsonl", engine="ragas", size=1,
                          snapshot=snapshot, single_hop_ratio=1, seed=11)
    pipeline.regenerate(Path(result.manifest), tmp_path / "second.jsonl", seed=42)
    assert calls[0]["knowledge_graph"] is None
    assert calls[1]["knowledge_graph"] is kg
    assert calls[1]["single_hop_ratio"] == 1
    assert calls[1]["seed"] == 42


def test_cli_generate_and_regenerate(tmp_path):
    first, second = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    assert main(["testgen", "--corpus", str(CORPUS), "--size", "3", "--out", str(first)]) == 0
    assert main(["testgen-regenerate", "--manifest", str(first.with_suffix(".manifest.json")),
                 "--out", str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


def test_publish_failure_restores_previous_bundle(tmp_path, monkeypatch):
    result = pipeline.run("jsonl", tmp_path / "first.jsonl", corpus=CORPUS, size=2)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    original_replace = pipeline.os.replace
    injected = False

    def fail_once(source, destination):
        nonlocal injected
        if str(destination).endswith(".graph.json") and not injected:
            injected = True
            raise OSError("simulated disk failure")
        original_replace(source, destination)

    monkeypatch.setattr(pipeline.os, "replace", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        pipeline.run("jsonl", Path(result.output), corpus=CORPUS, size=3, overwrite=True)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_regeneration_preserves_origin_identity(tmp_path, monkeypatch):
    result = pipeline.run("jsonl", tmp_path / "first.jsonl", corpus=CORPUS, size=2)
    original = json.loads(Path(result.manifest).read_text())["store_identity"]
    monkeypatch.setenv("QDRANT_COLLECTION", "unrelated_collection")
    repeated = pipeline.regenerate(Path(result.manifest), tmp_path / "second.jsonl")
    assert json.loads(Path(repeated.manifest).read_text())["store_identity"] == original


def test_store_mutation_cli_requires_explicit_collection():
    assert main(["bench", "clean", "--qdrant"]) == 2
    assert main(["bench", "seed", "--name", "linkpaper-local"]) == 2

"""Vector retrieval and answer-generation integration without external services."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from linkpaper_eval.schemas import EvalCase
from linkpaper_eval.stores.records import ChunkRecord, SearchHit
from linkpaper_eval.targets.base import build_target
from linkpaper_eval.targets.vector_rag import VectorRagTarget


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    instance = VectorRagTarget(
        top_k=2, embedding={"provider": "hash", "dimensions": 64},
        qdrant={"url": ":memory:", "collection": "baseline-test"},
        generation={"model": "test-answer-model"},
    )
    yield instance
    instance.close()


def mock_answer(target, handler):
    target.client.close()
    target.client = httpx.Client(base_url="https://answer.test/v1", transport=httpx.MockTransport(handler))


def response(answer="Generated answer", citations=None):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": json.dumps({"answer": answer, "citations": citations or []})}}],
        "usage": {"prompt_tokens": 17, "completion_tokens": 9},
    })


def test_qdrant_retrieval_and_generation_use_no_reference_or_graph(target):
    pytest.importorskip("qdrant_client")
    chunks = [
        ChunkRecord.build("paper-a", 0, "Transformers use attention for translation."),
        ChunkRecord.build("paper-b", 0, "Bananas are fruit."),
    ]
    target.qdrant.ensure_collection(target.embedder.dimensions)
    target.qdrant.upsert_chunks(chunks, target.embedder.embed([chunk.text for chunk in chunks]))
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return response("Attention enables translation.", [chunks[0].chunk_id])
    mock_answer(target, handler)
    result = target.run(EvalCase(
        case_id="case", question="How do transformers translate?", paper_id="unrelated",
        gold_answer="SECRET_GOLD", gold_chunk_ids=["SECRET_CHUNK"],
        gold_paper_ids=["SECRET_PAPER"], must_include=["SECRET_TERM"],
    ))
    assert result.error is None
    assert result.answer == "Attention enables translation."
    assert result.retrieved[0].chunk_id == chunks[0].chunk_id
    assert all(item.retrieval_source == "qdrant_vector" for item in result.retrieved)
    assert result.scope == "global"
    assert result.usage.total_tokens == 26
    assert captured[0]["model"] == "test-answer-model"
    assert "SECRET" not in json.dumps(captured)
    prompt = json.loads(captured[0]["messages"][1]["content"])
    assert prompt["contexts"] == [{"chunk_id": item.chunk_id, "text": item.text} for item in result.retrieved]
    assert not hasattr(target, "_neo4j")


def test_generation_failure_retains_retrieved_evidence(target, monkeypatch):
    chunk = ChunkRecord.build("paper", 0, "Evidence text.")
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [SearchHit(chunk=chunk, score=0.8, rank=1)])
    mock_answer(target, lambda request: httpx.Response(503, json={"error": "unavailable"}))
    result = target.run(EvalCase(case_id="case", question="question"))
    assert "503" in result.error
    assert result.retrieved[0].text == "Evidence text."
    assert result.answer == ""


def test_model_cannot_cite_unretrieved_gold_chunk(target, monkeypatch):
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [])
    mock_answer(target, lambda request: response(citations=["gold-only"]))
    result = target.run(EvalCase(case_id="case", question="question", gold_chunk_ids=["gold-only"]))
    assert "not retrieved" in result.error
    assert result.citations == []


def test_missing_payload_text_is_a_target_error(target, monkeypatch):
    chunk = ChunkRecord(chunk_id="id", paper_id="paper", text="")
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [SearchHit(chunk=chunk, score=0.8)])
    result = target.run(EvalCase(case_id="case", question="question"))
    assert "evidence text" in result.error


def test_empty_retrieval_can_generate_an_abstention(target, monkeypatch):
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [])
    mock_answer(target, lambda request: response("Insufficient evidence."))
    result = target.run(EvalCase(case_id="case", question="question"))
    assert result.error is None
    assert result.answer == "Insufficient evidence."
    assert result.retrieved == []


def test_named_vector_factory_and_configuration_default_to_learned_embeddings(monkeypatch):
    from pathlib import Path
    from linkpaper_eval.config import load_config
    from linkpaper_eval.targets import vector_rag
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.delenv("LINKPAPER_EMBEDDING_PROVIDER", raising=False)
    captured = []
    def embedder(settings):
        captured.append(settings)
        return SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(vector_rag, "build_embedder", embedder)
    instance = build_target({"type": "vector_rag"})
    instance.close()
    assert captured[0].provider == "openai"
    config = load_config(Path(__file__).resolve().parents[1] / "configs/vector.yaml")
    assert config.target["type"] == "vector_rag"
    assert config.target["options"]["embedding"]["provider"] == "openai"
    assert "neo4j" not in config.target["options"]


@pytest.mark.parametrize("metadata", [
    {"embedding_model": "wrong-model", "embedding_dimension": 64},
    {"embedding_dimension": 128},
    {"embedding_dimensions": 128},
    {"embedding_provider": "different-provider"},
])
def test_embedding_signature_mismatch_fails_before_answer_generation(target, monkeypatch, metadata):
    chunk = ChunkRecord.build("paper", 0, "Evidence text.", metadata=metadata)
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [SearchHit(chunk=chunk, score=0.8)])
    def forbidden_answer_call(request):
        pytest.fail("An incompatible index must not reach the answer model")
    mock_answer(target, forbidden_answer_call)
    result = target.run(EvalCase(case_id="case", question="question"))
    assert "Qdrant embedding mismatch" in result.error
    assert result.answer == ""


def test_matching_embedding_signature_can_generate_answer(target, monkeypatch):
    chunk = ChunkRecord.build("paper", 0, "Evidence text.", metadata={
        "embedding_provider": "hash", "embedding_model": "hash", "embedding_dimension": 64,
    })
    monkeypatch.setattr(target.qdrant, "search", lambda vector, top_k: [SearchHit(chunk=chunk, score=0.8)])
    mock_answer(target, lambda request: response(citations=[chunk.chunk_id]))
    result = target.run(EvalCase(case_id="case", question="question"))
    assert result.error is None
    assert result.answer == "Generated answer"

"""Exercise the installed Ragas graph/transforms/prompts/executors without APIs."""

from __future__ import annotations

import asyncio
import json
import socket

import pytest

pytest.importorskip("ragas")

from langchain_core.outputs import Generation, LLMResult
from ragas.embeddings import BaseRagasEmbeddings
from ragas.llms import BaseRagasLLM
from ragas.run_config import RunConfig
from ragas.testset.persona import Persona

from linkpaper_eval import ragas_runtime
from linkpaper_eval.stores.records import ChunkRecord
from linkpaper_eval.testgen import ragas_engine
from linkpaper_eval.testgen.graph import ChunkGraph, ChunkLink


class ScriptedLLM(BaseRagasLLM):
    """Provider substitute; Ragas prompt serialization/parsing remain real."""

    def __init__(self):
        super().__init__(run_config=RunConfig(max_retries=0))
        self.prompts = []

    def generate_text(self, prompt, n=1, **kwargs):
        text = prompt.to_string()
        self.prompts.append(text)
        if text.startswith("Summarize the given text"):
            payload = {"text": "Research on retrieval quality and evidence."}
        elif text.startswith("Extract the main themes"):
            payload = {"output": ["retrieval quality", "evidence"]}
        elif text.startswith("Extract the named entities"):
            payload = {"entities": ["Alpha", "Beta"]}
        elif text.startswith("Using the provided summary"):
            payload = {"name": "Researcher", "role_description": "Studies evidence retrieval."}
        elif text.startswith("Generate a single-hop query"):
            payload = {"query": "What does the source report?", "answer": "The source reports retrieval evidence."}
        elif text.startswith("Generate a multi-hop query"):
            payload = {"query": "How do Alpha and Beta retrieval results compare?", "answer": "Alpha improves retrieval; Beta examines evidence."}
        else:
            raise AssertionError(f"Unexpected Ragas prompt: {text[:200]}")
        return LLMResult(generations=[[Generation(text=json.dumps(payload)) for _ in range(n)]])

    async def agenerate_text(self, prompt, n=1, **kwargs):
        return self.generate_text(prompt, n=n, **kwargs)

    def is_finished(self, response):
        return True


class LocalEmbeddings(BaseRagasEmbeddings):
    def __init__(self):
        super().__init__()
        self.run_config = RunConfig(max_retries=0)

    def embed_query(self, text):
        return [1.0, 0.0]

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    async def aembed_query(self, text):
        return self.embed_query(text)

    async def aembed_documents(self, texts):
        return self.embed_documents(texts)


@pytest.fixture
def source_graph():
    return ChunkGraph(
        chunks=[
            ChunkRecord(chunk_id="alpha", paper_id="arxiv:alpha", text="Alpha improves retrieval.", chunk_index=0),
            ChunkRecord(chunk_id="beta", paper_id="arxiv:beta", text="Beta examines evidence.", chunk_index=0),
        ],
        links=[ChunkLink(source="alpha", target="beta", type="cites", metadata={"relation_type": "CITES"})],
    )


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")

    def no_network(*args, **kwargs):
        raise AssertionError("This integration test must not use the network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    llm = ScriptedLLM()
    embeddings = LocalEmbeddings()
    monkeypatch.setattr(ragas_engine, "build_llm", lambda *args, **kwargs: llm)
    monkeypatch.setattr(ragas_engine, "build_embeddings", lambda *args, **kwargs: embeddings)
    return llm, embeddings


def test_real_ragas_transforms_generation_and_reuse(tmp_path, monkeypatch, source_graph, provider):
    llm, _ = provider
    path = tmp_path / "knowledge_graph.json"
    result = ragas_engine.generate(source_graph, size=3, single_hop_ratio=1 / 3, knowledge_graph_path=path)
    rows = result.to_list()
    assert len(rows) == 3
    assert [row["synthesizer_name"] for row in rows] == ["linkpaper_single_hop", "linkpaper_multi_hop", "linkpaper_multi_hop"]
    source_text = {chunk.chunk_id: chunk.text for chunk in source_graph.chunks}
    for row in rows:
        assert row["reference_contexts"] == [source_text[chunk_id] for chunk_id in row["reference_context_ids"]]
    assert rows[1]["reference_context_ids"] == ["alpha", "beta"]
    assert any('"relationship_type": "cites"' in prompt for prompt in llm.prompts)

    kg = ragas_engine.load_knowledge_graph(path)
    assert all(node.type.name == "CHUNK" and node.properties["summary_embedding"] for node in kg.nodes)
    assert kg.relationships[0].type == "linkpaper_cites"
    assert not kg.relationships[0].bidirectional
    assert "entities_overlap_score" not in kg.relationships[0].properties

    def cannot_rebuild(*args, **kwargs):
        raise AssertionError("Saved enriched graph must be reused")

    monkeypatch.setattr(ragas_engine, "build_knowledge_graph", cannot_rebuild)
    reused = ragas_engine.generate(source_graph, size=2, single_hop_ratio=1, knowledge_graph=kg)
    assert len(reused.samples) == 2
    assert all(row["synthesizer_name"] == "linkpaper_single_hop" for row in reused.to_list())


def test_real_ragas_graph_scenario_uses_only_stored_edges(source_graph, provider):
    llm, embeddings = provider
    kg = ragas_engine.build_knowledge_graph(source_graph, llm, embeddings)
    _, multi = ragas_engine._query_synthesizers(llm, seed=12)
    personas = [Persona(name="Researcher", role_description="Studies papers.")]
    scenarios = asyncio.run(multi.generate_scenarios(5, kg, personas))
    assert len(scenarios) == 5
    assert all([node.properties["document_metadata"]["chunk_id"] for node in item.nodes] == ["alpha", "beta"] for item in scenarios)
    assert all(item.relationship_type == "cites" for item in scenarios)


def test_requested_multi_hop_without_edges_fails(source_graph, provider):
    source_graph.links = []
    with pytest.raises(ValueError, match="실제 그래프 간선"):
        ragas_engine.generate(source_graph, size=1, single_hop_ratio=0)


@pytest.mark.parametrize("ratio", [-0.1, 1.1, float("nan")])
def test_invalid_distribution_rejected_before_provider_use(source_graph, ratio):
    with pytest.raises(ValueError, match="single_hop_ratio"):
        ragas_engine.generate(source_graph, single_hop_ratio=ratio)


def test_enrichment_failure_is_not_silently_skipped(source_graph, provider):
    llm, embeddings = provider
    kg = ragas_engine.build_knowledge_graph(source_graph, llm, embeddings, apply_transforms=False)
    with pytest.raises(ValueError, match="summary"):
        ragas_engine.generate(source_graph, size=1, knowledge_graph=kg)


def test_runtime_adapters_match_real_ragas_protocol(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-not-a-real-key")
    assert isinstance(ragas_runtime.build_llm(), BaseRagasLLM)
    assert isinstance(ragas_runtime.build_embeddings(), BaseRagasEmbeddings)


def test_unsupported_ragas_version_has_actionable_error(monkeypatch):
    monkeypatch.setattr(ragas_runtime, "ragas_version", lambda: "0.4.0")
    with pytest.raises(RuntimeError, match="0.3.9"):
        ragas_runtime.require_ragas()

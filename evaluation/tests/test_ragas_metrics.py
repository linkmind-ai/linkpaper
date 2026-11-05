"""Ragas result contracts and failure accounting without paid API calls."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from linkpaper_eval.benchmark import ragas_metrics as scoring


@pytest.fixture
def ragas_stub(monkeypatch):
    calls = []
    native_names = {
        "faithfulness": "faithfulness",
        "answer_relevancy": "answer_relevancy",
        "context_precision": "llm_context_precision_with_reference",
        "context_recall": "context_recall",
    }
    values = {name: 0.75 for name in native_names}
    ragas = ModuleType("ragas")
    schema = ModuleType("ragas.dataset_schema")
    schema.SingleTurnSample = SimpleNamespace
    ragas.EvaluationDataset = SimpleNamespace

    def evaluate(**kwargs):
        calls.append(kwargs)
        metric = kwargs["metrics"][0]
        name = next(name for name, native in native_names.items() if native == metric.name)
        value = values[name]
        if isinstance(value, Exception):
            raise value
        # Deliberately not a mapping: dict(EvaluationResult) is unsupported.
        return SimpleNamespace(scores=[
            {metric.name: value} for _ in kwargs["dataset"].samples
        ])

    ragas.evaluate = evaluate
    monkeypatch.setitem(sys.modules, "ragas", ragas)
    monkeypatch.setitem(sys.modules, "ragas.dataset_schema", schema)
    monkeypatch.setattr(scoring, "require_ragas", lambda: None)
    monkeypatch.setattr(scoring, "ragas_version", lambda: "0.3.9")
    monkeypatch.setattr(scoring, "build_llm", lambda model: "judge")
    monkeypatch.setattr(scoring, "build_embeddings", lambda: "embeddings")
    monkeypatch.setattr(scoring, "_build_metric", lambda name, llm, embeddings: SimpleNamespace(name=native_names[name]))
    return calls, values


def write_cases(tmp_path: Path, rows: list[dict]) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "cases.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    return run


def sample(**overrides) -> dict:
    return {
        "case_id": "one", "question": "What model?", "answer": "A transformer.",
        "retrieved_chunk_ids": ["chunk-a"],
        "retrieved_contexts": ["We use a transformer."],
        "reference": "A transformer.", **overrides,
    }


def test_all_four_metrics_use_saved_evidence_and_canonical_names(tmp_path, ragas_stub):
    calls, _ = ragas_stub
    run = write_cases(tmp_path, [sample()])
    report = scoring.score_run(run, model="test-judge")
    assert report.status == "complete"
    assert report.sample_count == 1
    assert report.judge_model == "test-judge"
    assert report.ragas_version == "0.3.9"
    assert report.metric_counts == {f"ragas.{name}": 1 for name in scoring.DEFAULT_METRICS}
    assert report.aggregate == {f"ragas.{name}": 0.75 for name in scoring.DEFAULT_METRICS}
    assert len(calls) == 4
    assert all(call["dataset"].samples[0].retrieved_contexts == ["We use a transformer."] for call in calls)
    assert all(call["dataset"].samples[0].reference == "A transformer." for call in calls)
    saved = json.loads((run / "ragas.json").read_text())
    assert saved["status"] == "complete"
    assert saved["judge_model"] == "test-judge"
    assert saved["ragas_version"] == "0.3.9"


def test_missing_reference_does_not_score_reference_metrics(tmp_path, ragas_stub):
    calls, _ = ragas_stub
    report = scoring.score_run(write_cases(tmp_path, [sample(reference=None)]))
    assert report.status == "partial"
    assert report.metric_counts["ragas.context_precision"] == 0
    assert report.metric_counts["ragas.context_recall"] == 0
    assert set(report.aggregate) == {"ragas.faithfulness", "ragas.answer_relevancy"}
    assert "Missing reference" in report.cases[0].errors["ragas.context_recall"]
    assert len(calls) == 2


def test_nonfinite_scores_are_errors_and_excluded_from_denominator(tmp_path, ragas_stub):
    _, values = ragas_stub
    values["faithfulness"] = float("nan")
    values["context_recall"] = float("inf")
    run = write_cases(tmp_path, [sample()])
    report = scoring.score_run(run)
    assert report.status == "partial"
    assert report.metric_counts["ragas.faithfulness"] == 0
    assert "ragas.faithfulness" not in report.aggregate
    assert "non-finite" in report.cases[0].errors["ragas.faithfulness"]
    text = (run / "ragas.json").read_text()
    assert "NaN" not in text and "Infinity" not in text


def test_metric_failure_is_saved_and_does_not_discard_other_metrics(tmp_path, ragas_stub):
    _, values = ragas_stub
    values["context_precision"] = RuntimeError("judge unavailable")
    report = scoring.score_run(write_cases(tmp_path, [sample()]))
    assert report.status == "partial"
    assert "judge unavailable" in report.cases[0].errors["ragas.context_precision"]
    assert report.metric_counts["ragas.answer_relevancy"] == 1


def test_legacy_corpus_restores_all_contexts_in_rank_order(tmp_path, ragas_stub):
    calls, _ = ragas_stub
    row = sample(retrieved_chunk_ids=["b", "a"], reference=None)
    del row["retrieved_contexts"]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"chunk_id":"a","text":"A"}\n{"chunk_id":"b","text":"B"}\n')
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"case_id":"one","gold_answer":"Reference"}\n')
    report = scoring.score_run(write_cases(tmp_path, [row]), corpus, dataset)
    assert report.status == "complete"
    assert calls[0]["dataset"].samples[0].retrieved_contexts == ["B", "A"]
    assert calls[0]["dataset"].samples[0].reference == "Reference"


def test_partial_context_reconstruction_is_not_judged(tmp_path, ragas_stub):
    row = sample(retrieved_chunk_ids=["a", "missing"])
    del row["retrieved_contexts"]
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text('{"chunk_id":"a","text":"A"}\n')
    report = scoring.score_run(write_cases(tmp_path, [row]), corpus)
    assert report.metric_counts["ragas.context_recall"] == 0
    assert report.metric_counts["ragas.answer_relevancy"] == 1


def test_empty_retrieval_counts_as_zero_precision_and_recall(tmp_path, ragas_stub):
    report = scoring.score_run(write_cases(tmp_path, [sample(
        retrieved_contexts=[], retrieved_chunk_ids=[]
    )]))
    assert report.aggregate["ragas.context_precision"] == 0
    assert report.aggregate["ragas.context_recall"] == 0
    assert report.metric_counts["ragas.context_recall"] == 1


def test_empty_or_failed_run_still_writes_report(tmp_path, ragas_stub):
    calls, _ = ragas_stub
    run = write_cases(tmp_path, [sample(error="target unavailable")])
    report = scoring.score_run(run)
    assert report.status == "failed"
    assert report.skipped == 1
    assert report.aggregate == {}
    assert (run / "ragas.json").exists()
    assert calls == []


def test_judge_setup_failure_is_saved_before_raising(tmp_path, ragas_stub, monkeypatch):
    def broken(model):
        raise RuntimeError("missing key")
    monkeypatch.setattr(scoring, "build_llm", broken)
    run = write_cases(tmp_path, [sample()])
    with pytest.raises(RuntimeError, match="missing key"):
        scoring.score_run(run)
    report = json.loads((run / "ragas.json").read_text())
    assert report["status"] == "failed"
    assert "Judge setup failed" in report["cases"][0]["errors"]["ragas.faithfulness"]


def test_saved_run_preserves_full_ranked_evidence_and_reference():
    from linkpaper_eval.config import EvalConfig
    from linkpaper_eval.runner import _score_case
    from linkpaper_eval.schemas import EvalCase, RetrievedItem, TargetResponse
    case = EvalCase(case_id="case", question="question", gold_answer="secret reference")
    items = [RetrievedItem(chunk_id=str(i), text=f"evidence {i}", rank=12-i) for i in range(12)]
    result = _score_case(case, TargetResponse(answer="answer", retrieved=items), None, EvalConfig(suite="generation", dataset="unused"))
    assert len(result.retrieved_chunk_ids) == 12
    assert result.retrieved_contexts == [f"evidence {i}" for i in range(11, -1, -1)]
    assert result.reference == "secret reference"


def test_pinned_ragas_classes_have_compatible_result_contract():
    pytest.importorskip("ragas")
    from ragas import EvaluationDataset
    from ragas.callbacks import ChainRun
    from ragas.dataset_schema import EvaluationResult, SingleTurnSample
    metrics = [scoring._build_metric(name, None, None) for name in scoring.DEFAULT_METRICS]
    assert [metric.name for metric in metrics] == [
        "faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall"
    ]
    trace = ChainRun(run_id="root", parent_run_id=None, name="evaluation", inputs={}, metadata={})
    result = EvaluationResult(
        scores=[{"faithfulness": 0.5}],
        dataset=EvaluationDataset(samples=[SingleTurnSample(user_input="q")]),
        ragas_traces={"root": trace},
    )
    assert result.scores == [{"faithfulness": 0.5}]


def test_real_ragas_evaluate_runs_all_four_metrics_with_scripted_provider(tmp_path, monkeypatch):
    """Exercise Ragas prompts, parsing, metrics, executor and result serialization."""
    pytest.importorskip("ragas")
    from langchain_core.outputs import Generation, LLMResult
    from ragas.embeddings import BaseRagasEmbeddings
    from ragas.llms import BaseRagasLLM
    from ragas.run_config import RunConfig

    monkeypatch.setenv("RAGAS_DO_NOT_TRACK", "true")

    class ScriptedJudge(BaseRagasLLM):
        def is_finished(self, response):
            return True

        def generate_text(self, prompt, n=1, **kwargs):
            text = prompt.to_string()
            if text.startswith("Given a question and an answer, analyze"):
                payload = {"statements": ["A transformer is used.", "The model uses lasers."]}
            elif text.startswith("Your task is to judge the faithfulness"):
                payload = {"statements": [
                    {"statement": "A transformer is used.", "reason": "Supported.", "verdict": 1},
                    {"statement": "The model uses lasers.", "reason": "Unsupported.", "verdict": 0},
                ]}
            elif text.startswith("Generate a question for the given answer"):
                payload = {"question": "What model?", "noncommittal": 0}
            elif text.startswith("Given question, answer and context verify"):
                payload = {"reason": "Evidence check.", "verdict": 0 if "Bananas are fruit" in text else 1}
            elif text.startswith("Given a context, and an answer, analyze"):
                payload = {"classifications": [
                    {"statement": "A transformer is used.", "reason": "Supported.", "attributed": 1},
                    {"statement": "The model uses lasers.", "reason": "Unsupported.", "attributed": 0},
                ]}
            else:
                raise AssertionError(f"Unexpected judge prompt: {text[:80]}")
            return LLMResult(generations=[[Generation(text=json.dumps(payload)) for _ in range(n)]])

        async def agenerate_text(self, prompt, n=1, **kwargs):
            return self.generate_text(prompt, n=n, **kwargs)

    class ScriptedEmbeddings(BaseRagasEmbeddings):
        def embed_query(self, text):
            return [1.0, 0.0]

        def embed_documents(self, texts):
            return [self.embed_query(text) for text in texts]

        async def aembed_query(self, text):
            return self.embed_query(text)

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

    judge = ScriptedJudge(run_config=RunConfig(max_retries=0))
    embeddings = ScriptedEmbeddings()
    embeddings.set_run_config(RunConfig(max_retries=0))
    monkeypatch.setattr(scoring, "build_llm", lambda model: judge)
    monkeypatch.setattr(scoring, "build_embeddings", lambda: embeddings)
    report = scoring.score_run(write_cases(tmp_path, [sample(
        retrieved_chunk_ids=["a", "b"],
        retrieved_contexts=["We use a transformer.", "Bananas are fruit."],
        answer="A transformer is used. The model uses lasers.",
        reference="A transformer is used. The model uses lasers.",
    )]))
    assert report.status == "complete", report.model_dump()
    assert report.aggregate == pytest.approx({
        "ragas.faithfulness": 0.5,
        "ragas.answer_relevancy": 1.0,
        "ragas.context_precision": 1.0,
        "ragas.context_recall": 0.5,
    })

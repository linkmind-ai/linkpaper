"""Score saved responses with Ragas and preserve per-case judge failures.

The four default metrics are judged independently: a missing reference must not
prevent reference-free evaluation, and a failed judge call is never a zero score.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from linkpaper_eval.benchmark.download import read_jsonl
from linkpaper_eval.ragas_runtime import (
    build_embeddings, build_llm, ragas_version, require_ragas,
)

_METRIC_CANDIDATES: dict[str, tuple[str, ...]] = {
    "faithfulness": ("Faithfulness",),
    "answer_relevancy": ("ResponseRelevancy", "AnswerRelevancy"),
    "context_precision": ("LLMContextPrecisionWithReference", "ContextPrecision"),
    "context_recall": ("LLMContextRecall", "ContextRecall"),
    "factual_correctness": ("FactualCorrectness",),
    "semantic_similarity": ("SemanticSimilarity",),
}
DEFAULT_METRICS = (
    "faithfulness", "answer_relevancy", "context_precision", "context_recall"
)
_NEEDS_EMBEDDINGS = {"answer_relevancy", "semantic_similarity"}
_NEEDS_REFERENCE = {
    "context_precision", "context_recall", "factual_correctness", "semantic_similarity"
}
_NEEDS_CONTEXT = {"faithfulness", "context_precision", "context_recall"}


class RagasCaseScore(BaseModel):
    case_id: str
    scores: dict[str, float] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)


class RagasScoreReport(BaseModel):
    run_id: str
    judge_model: str | None = None
    ragas_version: str | None = None
    metrics: list[str] = Field(default_factory=list)
    aggregate: dict[str, float] = Field(default_factory=dict)
    metric_counts: dict[str, int] = Field(default_factory=dict)
    sample_count: int = 0
    skipped: int = 0
    status: Literal["complete", "partial", "failed"] = "failed"
    warnings: list[str] = Field(default_factory=list)
    cases: list[RagasCaseScore] = Field(default_factory=list)


def _build_metric(name: str, llm: Any, embeddings: Any) -> Any:
    import ragas.metrics as ragas_metrics

    for class_name in _METRIC_CANDIDATES[name]:
        cls = getattr(ragas_metrics, class_name, None)
        if cls is None:
            continue
        kwargs: dict[str, Any] = {}
        if name != "semantic_similarity":
            kwargs["llm"] = llm
        if name in _NEEDS_EMBEDDINGS:
            kwargs["embeddings"] = embeddings
        return cls(**kwargs)
    raise ValueError(f"ragas에서 지표를 찾을 수 없습니다: {name}")


def _load_corpus_texts(corpus_path: Path | None) -> dict[str, str]:
    if corpus_path is None:
        return {}
    return {
        row["chunk_id"]: row.get("text", "")
        for row in read_jsonl(corpus_path)
        if row.get("chunk_id")
    }


def _load_references(dataset_path: Path | None) -> dict[str, str]:
    if dataset_path is None:
        return {}
    return {
        row["case_id"]: row["gold_answer"]
        for row in read_jsonl(dataset_path)
        if row.get("case_id") and row.get("gold_answer")
    }


def _contexts(row: dict[str, Any], texts: dict[str, str]) -> list[str] | None:
    """Prefer saved evidence; do not silently judge a partial reconstruction."""
    ids = row.get("retrieved_chunk_ids") or []
    if "retrieved_contexts" in row:
        contexts = row["retrieved_contexts"]
        if not isinstance(contexts, list):
            return None
        if ids and len(contexts) != len(ids):
            return None
    elif ids and all(chunk_id in texts for chunk_id in ids):
        contexts = [texts[chunk_id] for chunk_id in ids]
    else:
        return None
    if any(not isinstance(value, str) or not value.strip() for value in contexts):
        return None
    return contexts


def _save_report(run_dir: Path, report: RagasScoreReport) -> RagasScoreReport:
    report.sample_count = sum(bool(case.scores) for case in report.cases)
    report.skipped = len(report.cases) - report.sample_count
    for metric in report.metrics:
        key = f"ragas.{metric}"
        values = [case.scores[key] for case in report.cases if key in case.scores]
        report.metric_counts[key] = len(values)
        if values:
            report.aggregate[key] = sum(values) / len(values)
        else:
            report.warnings.append(f"{key}: 유효한 점수가 없습니다.")
    if report.aggregate:
        report.status = "partial" if any(case.errors for case in report.cases) else "complete"
    (run_dir / "ragas.json").write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return report


def score_run(
    run_dir: Path,
    corpus_path: Path | None = None,
    dataset_path: Path | None = None,
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    model: str = "gpt-4o-mini",
    limit: int | None = None,
) -> RagasScoreReport:
    """Judge saved run evidence; legacy runs can restore texts from a corpus.

    Missing inputs and non-finite judge results are recorded per metric and
    excluded from its denominator. An explicitly empty retrieval has context
    precision/recall zero, so retrieval failures cannot inflate the mean.
    """
    if not metrics or len(set(metrics)) != len(metrics):
        raise ValueError("Choose at least one unique Ragas metric.")
    unknown = set(metrics) - _METRIC_CANDIDATES.keys()
    if unknown:
        raise ValueError(f"Unknown Ragas metrics: {sorted(unknown)}")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    cases_path = run_dir / "cases.jsonl"
    if not cases_path.exists():
        raise FileNotFoundError(f"실행 결과를 찾을 수 없습니다: {cases_path}")
    require_ragas()
    from ragas import EvaluationDataset, evaluate
    from ragas.dataset_schema import SingleTurnSample

    texts = _load_corpus_texts(corpus_path)
    references = _load_references(dataset_path)
    report = RagasScoreReport(
        run_id=run_dir.name, judge_model=model, ragas_version=ragas_version(),
        metrics=list(metrics),
    )
    eligible: dict[str, list[tuple[RagasCaseScore, Any]]] = {name: [] for name in metrics}

    for row in read_jsonl(cases_path)[:limit]:
        case = RagasCaseScore(case_id=row.get("case_id", ""))
        report.cases.append(case)
        contexts = _contexts(row, texts)
        reference = row.get("reference") or references.get(case.case_id)
        answer = (row.get("answer") or "").strip()
        question = (row.get("question") or "").strip()
        for name in metrics:
            key = f"ragas.{name}"
            error = None
            if row.get("error"):
                error = f"Target failed: {row['error']}"
            elif not question:
                error = "Missing question"
            elif not answer:
                error = "Missing generated answer"
            elif name in _NEEDS_REFERENCE and not (reference or "").strip():
                error = "Missing reference answer"
            elif name in _NEEDS_CONTEXT and contexts is None:
                error = "Missing or incomplete retrieved context text"
            if error:
                case.errors[key] = error
                continue
            if contexts == [] and name in {"context_precision", "context_recall"}:
                case.scores[key] = 0.0
                continue
            sample = SingleTurnSample(
                user_input=question, response=answer,
                retrieved_contexts=contexts, reference=reference,
            )
            eligible[name].append((case, sample))

    if not any(eligible.values()):
        return _save_report(run_dir, report)

    try:
        llm = build_llm(model)
        embeddings = (
            build_embeddings()
            if any(eligible.get(name) for name in _NEEDS_EMBEDDINGS) else None
        )
    except Exception as exc:
        for name, rows in eligible.items():
            for case, _ in rows:
                case.errors[f"ragas.{name}"] = f"Judge setup failed: {type(exc).__name__}: {exc}"
        _save_report(run_dir, report)
        raise

    for name, rows in eligible.items():
        if not rows:
            continue
        key = f"ragas.{name}"
        try:
            metric = _build_metric(name, llm, embeddings)
            result = evaluate(
                dataset=EvaluationDataset(samples=[sample for _, sample in rows]),
                metrics=[metric], llm=llm, embeddings=embeddings,
                raise_exceptions=False, show_progress=False,
            )
            # EvaluationResult is a dataclass, not an aggregate mapping. Its
            # public scores list also retains the row-level failure locations.
            scores = result.scores
            if len(scores) != len(rows):
                raise ValueError("Ragas returned a different number of score rows")
            for (case, _), values in zip(rows, scores):
                value = values.get(metric.name)
                try:
                    score = float(value)
                except (TypeError, ValueError):
                    score = math.nan
                if not math.isfinite(score):
                    case.errors[key] = "Judge returned a missing or non-finite score"
                else:
                    case.scores[key] = score
        except Exception as exc:
            for case, _ in rows:
                case.errors[key] = f"Judge failed: {type(exc).__name__}: {exc}"

    return _save_report(run_dir, report)

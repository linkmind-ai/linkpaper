"""ragas 지표로 실행 결과를 사후 채점한다.

기존 지표는 결정적이고 비용이 0이지만 어휘 기반이라 한계가 있다.
`groundedness_lexical`이 1.0이어도 답변이 질문에 답하지 못할 수 있다.
ragas 지표는 LLM 심판을 써서 그 간극을 메운다.

실행 중이 아니라 실행이 끝난 뒤에 채점한다. 이유는 두 가지다.

1. `runner.run_suite`를 건드리지 않는다. 기존 실행 경로에 LLM 호출이
   끼어들면 오프라인 CI가 깨진다.
2. 같은 실행 결과를 여러 번 다시 채점할 수 있다. 지표나 심판 모델을
   바꿔 볼 때 파이프라인을 다시 돌릴 필요가 없다.

점수는 `runs/<run_id>/ragas.json`에 저장하고 `ragas.` 접두사를 붙여
결정적 지표와 섞이지 않게 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.benchmark.download import read_jsonl
from linkpaper_eval.ragas_runtime import build_embeddings, build_llm, require_ragas

# 지표 이름 → ragas 클래스 후보. ragas 버전에 따라 이름이 달라서
# 후보를 순서대로 시도한다.
_METRIC_CANDIDATES: dict[str, tuple[str, ...]] = {
    "faithfulness": ("Faithfulness",),
    "answer_relevancy": ("ResponseRelevancy", "AnswerRelevancy"),
    "context_precision": (
        "LLMContextPrecisionWithReference",
        "ContextPrecision",
    ),
    "context_recall": ("LLMContextRecall", "ContextRecall"),
    "factual_correctness": ("FactualCorrectness",),
    "semantic_similarity": ("SemanticSimilarity",),
}

DEFAULT_METRICS = ("faithfulness", "answer_relevancy", "context_recall")

# 임베딩이 반드시 있어야 동작하는 지표.
_NEEDS_EMBEDDINGS = {"answer_relevancy", "semantic_similarity"}


class RagasScoreReport(BaseModel):
    run_id: str
    metrics: list[str] = Field(default_factory=list)
    aggregate: dict[str, float] = Field(default_factory=dict)
    sample_count: int = 0
    skipped: int = 0
    warnings: list[str] = Field(default_factory=list)


def _build_metric(name: str, llm: Any, embeddings: Any) -> Any:
    import ragas.metrics as ragas_metrics

    for class_name in _METRIC_CANDIDATES.get(name, (name,)):
        cls = getattr(ragas_metrics, class_name, None)
        if cls is None:
            continue
        kwargs: dict[str, Any] = {"llm": llm}
        if name in _NEEDS_EMBEDDINGS and embeddings is not None:
            kwargs["embeddings"] = embeddings
        try:
            return cls(**kwargs)
        except TypeError:
            # 일부 지표는 llm을 생성자에서 받지 않는다.
            try:
                return cls()
            except Exception:  # noqa: BLE001 - 다음 후보로 넘어간다
                continue
    raise ValueError(f"ragas에서 지표를 찾을 수 없습니다: {name}")


def _load_corpus_texts(corpus_path: Path | None) -> dict[str, str]:
    if corpus_path is None or not corpus_path.exists():
        return {}
    return {
        row["chunk_id"]: row.get("text", "")
        for row in read_jsonl(corpus_path)
        if row.get("chunk_id")
    }


def _load_references(dataset_path: Path | None) -> dict[str, str]:
    if dataset_path is None or not dataset_path.exists():
        return {}
    references: dict[str, str] = {}
    for row in read_jsonl(dataset_path):
        answer = row.get("gold_answer")
        if row.get("case_id") and answer:
            references[row["case_id"]] = answer
    return references


def score_run(
    run_dir: Path,
    corpus_path: Path | None = None,
    dataset_path: Path | None = None,
    metrics: tuple[str, ...] = DEFAULT_METRICS,
    model: str = "gpt-4o-mini",
    limit: int | None = None,
) -> RagasScoreReport:
    """`runs/<run_id>/cases.jsonl`을 ragas로 채점한다.

    검색 근거 텍스트는 `cases.jsonl`에 없으므로 코퍼스에서 `chunk_id`로
    복원한다. 코퍼스를 주지 않으면 컨텍스트 없이 채점되고, 컨텍스트가
    필요한 지표는 의미가 없어지므로 경고를 남긴다.
    """
    require_ragas()

    from ragas import EvaluationDataset, evaluate
    from ragas.dataset_schema import SingleTurnSample

    cases_path = run_dir / "cases.jsonl"
    if not cases_path.exists():
        raise FileNotFoundError(f"실행 결과를 찾을 수 없습니다: {cases_path}")

    report = RagasScoreReport(run_id=run_dir.name, metrics=list(metrics))
    texts = _load_corpus_texts(corpus_path)
    references = _load_references(dataset_path)
    if not texts:
        report.warnings.append(
            "코퍼스를 찾지 못해 retrieved_contexts가 비어 있습니다. "
            "context_* 와 faithfulness 점수는 신뢰할 수 없습니다."
        )

    samples = []
    for row in read_jsonl(cases_path):
        if limit is not None and len(samples) >= limit:
            break
        if row.get("error"):
            report.skipped += 1
            continue
        answer = (row.get("answer") or "").strip()
        if not answer:
            report.skipped += 1
            continue

        contexts = [
            texts[chunk_id]
            for chunk_id in row.get("retrieved_chunk_ids") or []
            if chunk_id in texts
        ]
        samples.append(
            SingleTurnSample(
                user_input=row.get("question", ""),
                response=answer,
                retrieved_contexts=contexts,
                reference=references.get(row.get("case_id", ""), ""),
            )
        )

    report.sample_count = len(samples)
    if not samples:
        report.warnings.append("채점할 샘플이 없습니다.")
        return report

    llm = build_llm(model)
    embeddings = None
    if any(name in _NEEDS_EMBEDDINGS for name in metrics):
        embeddings = build_embeddings()

    metric_objects = [_build_metric(name, llm, embeddings) for name in metrics]
    result = evaluate(
        dataset=EvaluationDataset(samples=samples),
        metrics=metric_objects,
        llm=llm,
    )

    scores = dict(result)
    report.aggregate = {
        f"ragas.{key}": float(value)
        for key, value in scores.items()
        if isinstance(value, (int, float))
    }

    (run_dir / "ragas.json").write_text(
        json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report

"""집계 표본 수와 리포트의 분모 표시 회귀 테스트."""

from __future__ import annotations

import math

import pytest

from linkpaper_eval.metrics import (
    aggregate,
    aggregate_by_tag,
    metric_counts,
    metric_counts_by_tag,
)
from linkpaper_eval.report import render
from linkpaper_eval.schemas import CaseResult, RunManifest, RunResult


@pytest.fixture
def cases() -> list[CaseResult]:
    return [
        CaseResult(
            case_id="hit",
            question="q",
            metrics={"retrieval.recall@5": 1.0, "retrieval.ndcg@10": 0.5},
            tags=["lookup", "lookup", "all"],
        ),
        CaseResult(
            case_id="miss",
            question="q",
            metrics={"retrieval.recall@5": 0.0, "retrieval.ndcg@10": float("nan")},
            tags=["lookup", "all"],
        ),
        CaseResult(case_id="unlabelled", question="q", tags=["all"]),
        CaseResult(case_id="failed", question="q", error="timeout", tags=["all"]),
    ]


def _run(cases: list[CaseResult], **kwargs: object) -> RunResult:
    return RunResult(
        manifest=RunManifest(
            run_id="counts",
            suite="retrieval",
            target="test",
            dataset="test.jsonl",
            dataset_sha256="data",
            config_sha256="config",
            started_at="2026-10-16T00:00:00Z",
            case_count=len(cases),
        ),
        aggregate=aggregate(cases),
        by_tag=aggregate_by_tag(cases),
        cases=cases,
        **kwargs,
    )


def test_counts_follow_metric_denominators_including_zero(cases: list[CaseResult]) -> None:
    assert metric_counts(cases) == {"retrieval.ndcg@10": 1, "retrieval.recall@5": 2}
    scores = aggregate(cases)
    assert scores["retrieval.recall@5"] == pytest.approx(0.5)
    assert scores["retrieval.ndcg@10"] == pytest.approx(0.5)
    assert scores["operational.case_count"] == 4
    assert scores["operational.error_rate"] == pytest.approx(0.25)


def test_duplicate_tags_do_not_reweight_cases(cases: list[CaseResult]) -> None:
    scores = aggregate_by_tag(cases)
    counts = metric_counts_by_tag(cases)

    assert scores["lookup"]["retrieval.recall@5"] == pytest.approx(0.5)
    assert scores["lookup"]["operational.case_count"] == 2
    assert scores["all"]["operational.case_count"] == 4
    assert counts["lookup"] == counts["all"] == {
        "retrieval.ndcg@10": 1,
        "retrieval.recall@5": 2,
    }


def test_counts_exclude_nan_but_do_not_silently_remove_infinity() -> None:
    cases = [
        CaseResult(
            case_id="nonfinite",
            question="q",
            metrics={"custom.nan": float("nan"), "custom.inf": float("inf")},
        )
    ]
    assert metric_counts(cases) == {"custom.inf": 1}
    assert "custom.nan" not in aggregate(cases)
    assert math.isinf(aggregate(cases)["custom.inf"])


def test_empty_inputs_have_no_metric_counts() -> None:
    assert metric_counts([]) == {}
    assert metric_counts_by_tag([]) == {}
    assert aggregate_by_tag([]) == {}


def test_report_derives_counts_for_older_runs(cases: list[CaseResult]) -> None:
    result = _run(cases)
    text = render(result, baseline={"retrieval.recall@5": 0.4})

    assert "| 지표 | 값 | 평가 표본 | 베이스라인 | 변화 |" in text
    assert "| `retrieval.recall@5` | 0.5000 | 2 | 0.4000 | +0.1000 |" in text
    assert "| `retrieval.ndcg@10` | 0.5000 | 1 | — | — |" in text
    assert "| `operational.error_rate` | 0.2500 | — | — | — |" in text
    assert "| lookup | 2 | 0.5000 (n=2) | 0.5000 (n=1) |" in text
    assert "실패 케이스와 해당 정답이 없는 케이스를 제외" in text


def test_report_prefers_persisted_counts(cases: list[CaseResult]) -> None:
    result = _run(
        cases,
        metric_counts={"retrieval.recall@5": 8, "retrieval.ndcg@10": 4},
        by_tag_metric_counts={
            "lookup": {"retrieval.recall@5": 7, "retrieval.ndcg@10": 3}
        },
    )
    text = render(result)

    assert "| `retrieval.recall@5` | 0.5000 | 8 | — | — |" in text
    assert "| `retrieval.ndcg@10` | 0.5000 | 4 | — | — |" in text
    assert "| lookup | 2 | 0.5000 (n=7) | 0.5000 (n=3) |" in text
    assert "| all | 4 | 0.5000 (n=—) | 0.5000 (n=—) |" in text


def test_report_unknown_denominators_are_not_fabricated(cases: list[CaseResult]) -> None:
    result = _run(cases)
    result.cases = []
    text = render(result)

    assert "| `retrieval.recall@5` | 0.5000 | — | — | — |" in text
    assert "| lookup | 2 | 0.5000 (n=—) | 0.5000 (n=—) |" in text

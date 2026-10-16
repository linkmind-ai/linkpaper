"""응답 순위, 정답 등급과 저장 결과가 실제 평가에 그대로 반영되는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linkpaper_eval.cli import _load_run, main
from linkpaper_eval.config import EvalConfig, load_config
from linkpaper_eval.runner import _score_case, run_suite, save_run
from linkpaper_eval.schemas import EvalCase, RetrievedItem, TargetResponse

ROOT = Path(__file__).resolve().parents[1]


def test_duplicate_results_do_not_promote_later_hits() -> None:
    case = EvalCase(case_id="duplicate", question="q", gold_chunk_ids=["gold"])
    response = TargetResponse(retrieved=[
        RetrievedItem(chunk_id="gold", rank=3),
        RetrievedItem(chunk_id="noise", rank=1),
        RetrievedItem(chunk_id="noise", rank=2),
    ])
    config = EvalConfig(suite="retrieval", dataset="unused", k_values=[2, 3])

    result = _score_case(case, response, None, config)

    assert result.retrieved_chunk_ids == ["noise", "noise", "gold"]
    assert result.metrics["retrieval.recall@2"] == 0.0
    assert result.metrics["retrieval.precision@3"] == pytest.approx(1 / 3)
    assert result.metrics["retrieval.mrr"] == pytest.approx(1 / 3)
    assert result.metrics["retrieval.ap"] == pytest.approx(1 / 3)
    assert [item.rank for item in response.retrieved] == [3, 1, 2]


def test_paper_hit_uses_the_same_rank_order_as_chunk_metrics() -> None:
    case = EvalCase(case_id="paper", question="q", gold_paper_ids=["paper-gold"])
    response = TargetResponse(retrieved=[
        RetrievedItem(chunk_id="c6", paper_id="paper-gold", rank=6),
        *[RetrievedItem(chunk_id=f"c{i}", paper_id="noise", rank=i)
          for i in range(1, 6)],
    ])
    config = EvalConfig(suite="retrieval", dataset="unused")

    result = _score_case(case, response, None, config)

    assert result.metrics["retrieval.paper_hit@5"] == 0.0
    assert result.retrieved_chunk_ids == [f"c{i}" for i in range(1, 7)]


def test_partial_rank_information_keeps_array_order() -> None:
    response = TargetResponse(retrieved=[
        RetrievedItem(chunk_id="a", rank=2),
        RetrievedItem(chunk_id="a"),
        RetrievedItem(chunk_id="b", rank=1),
    ])
    assert response.ranked_chunk_ids() == ["a", "a", "b"]


def test_explicit_zero_grade_overrides_binary_gold_membership() -> None:
    case = EvalCase(
        case_id="graded", question="q", gold_chunk_ids=["excluded", "binary"],
        grades={"excluded": 0, "graded": 3},
    )
    assert case.graded_ids() == ["binary", "graded"]
    response = TargetResponse(retrieved=[RetrievedItem(chunk_id="excluded")])
    result = _score_case(case, response, None, EvalConfig(suite="retrieval", dataset="unused"))
    assert result.metrics["retrieval.recall@1"] == 0.0
    assert result.metrics["retrieval.precision@1"] == 0.0
    assert result.metrics["retrieval.ndcg@1"] == 0.0


def test_case_artifact_preserves_results_beyond_top_ten() -> None:
    case = EvalCase(case_id="long", question="q", gold_chunk_ids=["c11"])
    response = TargetResponse(retrieved=[
        RetrievedItem(chunk_id=f"c{i}") for i in range(1, 13)
    ])
    config = EvalConfig(suite="retrieval", dataset="unused", k_values=[11])

    result = _score_case(case, response, None, config)
    saved = json.loads(result.model_dump_json())

    assert saved["retrieved_chunk_ids"] == [f"c{i}" for i in range(1, 13)]
    assert result.metrics["retrieval.recall@11"] == 1.0


def test_saved_metric_counts_roundtrip_and_old_runs_remain_loadable(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/retrieval.yaml")
    result = run_suite(config, run_id="counts")
    run_dir = save_run(result, tmp_path)
    loaded = _load_run(run_dir)

    assert loaded is not None
    assert loaded.metric_counts["retrieval.recall@5"] == 12
    assert loaded.metric_counts == result.metric_counts
    assert loaded.by_tag_metric_counts == result.by_tag_metric_counts

    metrics_path = run_dir / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    del payload["metric_counts"], payload["by_tag_metric_counts"]
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    legacy = _load_run(run_dir)
    assert legacy is not None
    assert legacy.metric_counts == {}
    assert legacy.aggregate == result.aggregate


def test_cli_fails_missing_regression_baseline_and_preserves_report(tmp_path: Path) -> None:
    config = load_config(ROOT / "configs/retrieval.yaml")
    payload = config.model_dump(mode="json", exclude={"base_dir"})
    payload["dataset"] = str(config.resolve(config.dataset))
    payload["target"]["options"]["corpus"] = str(config.resolve(config.target["options"]["corpus"]))
    payload["baseline"] = str(tmp_path / "missing-baseline.json")
    payload["run"]["output_dir"] = str(tmp_path / "runs")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    args = ["run", "--config", str(config_path), "--run-id", "missing-baseline", "--quiet"]

    assert main(args) == 1
    report = (tmp_path / "runs/missing-baseline/report.md").read_text(encoding="utf-8")
    assert "❌" in report
    assert "retrieval.recall@5" in report
    assert main([*args, "--no-gates"]) == 0

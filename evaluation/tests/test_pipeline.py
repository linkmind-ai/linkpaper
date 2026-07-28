"""평가 파이프라인 통합 테스트.

설정 로딩부터 산출물 저장, 게이트 판정까지 한 번에 통과하는지 확인한다.
네트워크와 API 키 없이 돌아가야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from linkpaper_eval.config import GateRule, load_config
from linkpaper_eval.datasets import load_cases
from linkpaper_eval.gates import evaluate_gates, save_baseline
from linkpaper_eval.report import render
from linkpaper_eval.schemas import EvalCase
from linkpaper_eval.runner import run_suite, save_run

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def test_dataset_gold_ids_exist_in_corpus() -> None:
    """정답 청크 ID가 코퍼스에 실제로 존재하는지 검증한다.

    오타 하나로 Recall이 0이 되는 사고를 막는 가드다.
    """
    root = Path(__file__).resolve().parents[1]
    corpus_ids = {
        json.loads(line)["chunk_id"]
        for line in (root / "fixtures" / "mock_corpus.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    }

    for name in ("retrieval", "generation"):
        cases = load_cases(root / "datasets" / name / "sample.jsonl")
        for case in cases:
            for chunk_id in case.gold_chunk_ids:
                assert chunk_id in corpus_ids, f"{case.case_id}: unknown {chunk_id}"


def test_retrieval_suite_runs_end_to_end(tmp_path: Path) -> None:
    config = load_config(CONFIG_DIR / "retrieval.yaml")
    config.run.output_dir = str(tmp_path)
    config.baseline = None

    result = run_suite(config, run_id="test-run")

    assert result.manifest.case_count == 12
    assert result.manifest.target == "lexical_baseline"
    assert "retrieval.recall@5" in result.aggregate
    assert "routing.accuracy" in result.aggregate
    assert result.aggregate["operational.error_rate"] == 0.0

    run_dir = save_run(result, tmp_path)
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "cases.jsonl").exists()


def test_generation_suite_produces_judge_scores(tmp_path: Path) -> None:
    config = load_config(CONFIG_DIR / "generation.yaml")
    config.run.output_dir = str(tmp_path)
    config.baseline = None

    result = run_suite(config, run_id="test-gen")

    assert result.manifest.judge == "heuristic"
    assert "generation.citation_validity" in result.aggregate
    assert "judge.faithfulness" in result.aggregate
    # 베이스라인은 검색 결과만 인용하므로 인용 ID는 항상 유효해야 한다.
    assert result.aggregate["generation.citation_validity"] == 1.0


def test_extraction_suite_scores_triples(tmp_path: Path) -> None:
    config = load_config(CONFIG_DIR / "extraction.yaml")
    config.run.output_dir = str(tmp_path)
    config.baseline = None

    result = run_suite(config, run_id="test-ext")

    assert "extraction.triple_f1" in result.aggregate
    assert result.aggregate["extraction.evidence_attachment"] == 1.0


def test_named_target_swap_does_not_leak_options() -> None:
    """`--target http`로 바꿀 때 베이스라인 옵션이 딸려가면 안 된다.

    옵션은 타깃 종류마다 다르므로 병합하면 HttpBackendTarget이 `corpus`
    같은 인자를 받아 TypeError로 죽는다.
    """
    config = load_config(CONFIG_DIR / "retrieval.yaml")

    assert "corpus" in config.target["options"]

    http_spec = config.targets["http"]
    assert http_spec["type"] == "http_backend"
    assert "corpus" not in http_spec["options"]
    assert "base_url" in http_spec["options"]


def test_http_target_reports_errors_instead_of_raising() -> None:
    """백엔드가 없거나 501을 반환해도 실행이 중단되면 안 된다."""
    from linkpaper_eval.targets.http_backend import HttpBackendTarget

    target = HttpBackendTarget(base_url="http://127.0.0.1:1", timeout_s=1.0)
    response = target.run(EvalCase(case_id="x", question="q", paper_id="arxiv:1"))
    target.close()

    assert response.error is not None
    assert response.retrieved == []


def test_gates_fail_on_regression() -> None:
    aggregate = {"retrieval.recall@5": 0.50, "operational.error_rate": 0.0}
    baseline = {"retrieval.recall@5": 0.70}
    rules = {
        "retrieval.recall@5": GateRule(max_regression=0.05),
        "operational.error_rate": GateRule(max=0.05),
    }

    report = evaluate_gates(aggregate, rules, baseline)

    assert report.passed is False
    assert [outcome.metric for outcome in report.failures()] == ["retrieval.recall@5"]


def test_gates_treat_lower_is_better_metrics_correctly() -> None:
    aggregate = {"operational.error_rate": 0.30}
    baseline = {"operational.error_rate": 0.05}
    rules = {"operational.error_rate": GateRule(max_regression=0.10)}

    report = evaluate_gates(aggregate, rules, baseline)

    assert report.passed is False


def test_missing_metric_fails_gate_instead_of_passing_silently() -> None:
    report = evaluate_gates({}, {"retrieval.recall@5": GateRule(min=0.5)}, {})
    assert report.passed is False


def test_report_renders_markdown(tmp_path: Path) -> None:
    config = load_config(CONFIG_DIR / "retrieval.yaml")
    config.run.output_dir = str(tmp_path)
    config.baseline = None

    result = run_suite(config, run_id="test-report")
    gate_report = evaluate_gates(result.aggregate, config.gates, {})
    text = render(result, gate_report)

    assert "# 평가 리포트" in text
    assert "retrieval.recall@5" in text
    assert "취약 케이스" in text


def test_baseline_roundtrip(tmp_path: Path) -> None:
    config = load_config(CONFIG_DIR / "retrieval.yaml")
    config.run.output_dir = str(tmp_path)
    config.baseline = None

    result = run_suite(config, run_id="test-baseline")
    path = save_baseline(result, tmp_path / "baseline.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["suite"] == "retrieval"
    assert payload["aggregate"]["retrieval.recall@5"] == result.aggregate[
        "retrieval.recall@5"
    ]

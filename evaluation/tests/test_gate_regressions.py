"""Quality gates must never pass without valid evidence for every constraint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from linkpaper_eval.config import EvalConfig, GateRule, RunOptions, load_config
from linkpaper_eval.gates import evaluate_gates, load_baseline


METRIC = "retrieval.recall@5"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "rule",
    [GateRule(min=0.5), GateRule(max=1.0), GateRule(max_regression=0.05)],
)
def test_nonfinite_current_metric_fails_every_kind_of_gate(
    value: float, rule: GateRule
) -> None:
    report = evaluate_gates({METRIC: value}, {METRIC: rule}, {METRIC: 0.75})

    assert not report.passed
    assert len(report.failures()) == 1
    assert report.outcomes[0].value is None
    assert "유한한 숫자" in report.outcomes[0].reason
    # Invalid numbers cannot leak into JSON artifacts as NaN or Infinity.
    json.dumps(report.model_dump(), allow_nan=False)


@pytest.mark.parametrize("baseline", [None, {}, {"another.metric": 0.75}])
@pytest.mark.parametrize("absolute_min", [None, 0.5])
def test_regression_requires_baseline_even_when_absolute_threshold_passes(
    baseline: dict[str, float] | None, absolute_min: float | None
) -> None:
    report = evaluate_gates(
        {METRIC: 0.9},
        {METRIC: GateRule(min=absolute_min, max_regression=0.05)},
        baseline,
    )

    assert not report.passed
    assert "베이스라인 지표가 없습니다" in report.outcomes[0].reason


@pytest.mark.parametrize("reference", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_baseline_fails_regression(reference: float) -> None:
    report = evaluate_gates(
        {METRIC: 0.9},
        {METRIC: GateRule(min=0.5, max_regression=0.05)},
        {METRIC: reference},
    )

    assert not report.passed
    assert report.outcomes[0].baseline is None
    assert "베이스라인 지표가 유한한 숫자" in report.outcomes[0].reason
    json.dumps(report.model_dump(), allow_nan=False)


def test_missing_configured_baseline_cannot_silently_pass(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "retrieval.yaml"
    config_path.write_text(
        "suite: retrieval\n"
        "dataset: unused.jsonl\n"
        "baseline: baselines/missing.json\n"
        "gates:\n"
        f"  {METRIC}:\n"
        "    min: 0.5\n"
        "    max_regression: 0.05\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.baseline is not None
    baseline = load_baseline(config.resolve(config.baseline))

    report = evaluate_gates({METRIC: 0.9}, config.gates, baseline)

    assert not report.passed
    assert report.outcomes[0].baseline is None
    assert "베이스라인" in report.outcomes[0].reason


@pytest.mark.parametrize(
    "metric,current,reference",
    [
        (METRIC, 0.5, 0.75),
        (METRIC, 1.0, 0.75),
        ("operational.error_rate", 0.5, 0.25),
        ("operational.latency_p95_ms", 0.0, 0.25),
        ("operational.cost_usd", 0.0, 0.25),
    ],
)
def test_regression_boundary_and_improvements_pass(
    metric: str, current: float, reference: float
) -> None:
    report = evaluate_gates(
        {metric: current},
        {metric: GateRule(max_regression=0.25)},
        {metric: reference},
    )

    assert report.passed


def test_absolute_gates_do_not_require_baseline() -> None:
    report = evaluate_gates({METRIC: 0.75}, {METRIC: GateRule(min=0.5, max=1.0)})

    assert report.passed
    assert load_baseline(None) == {}


@pytest.mark.parametrize("wrapped", [False, True])
def test_baseline_loads_flat_and_run_artifact_formats(
    tmp_path: Path, wrapped: bool
) -> None:
    aggregate = {METRIC: 0.75, "operational.latency_p95_ms": 100}
    payload = {"run_id": "baseline", "aggregate": aggregate} if wrapped else aggregate
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_baseline(path) == aggregate


@pytest.mark.parametrize(
    "payload",
    [[], None, {"aggregate": []}, {"aggregate": None}],
)
def test_baseline_requires_metric_mapping(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        load_baseline(path)


@pytest.mark.parametrize("value", [None, True, "0.75", float("nan"), float("inf")])
def test_baseline_rejects_invalid_metric_values(tmp_path: Path, value: object) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"aggregate": {METRIC: value}}), encoding="utf-8")

    with pytest.raises(ValueError, match="finite number"):
        load_baseline(path)


@pytest.mark.parametrize("field", ["min", "max", "max_regression"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_gate_thresholds_must_be_finite(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        GateRule.model_validate({field: value})


@pytest.mark.parametrize(
    "rule", [{}, {"min": 0.9, "max": 0.5}, {"max_regression": -0.01}]
)
def test_gate_rejects_empty_or_contradictory_constraints(rule: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        GateRule.model_validate(rule)


@pytest.mark.parametrize("cutoffs", [[], [0], [-1], [1, 1], [1.5]])
def test_retrieval_cutoffs_must_be_positive_unique_integers(
    cutoffs: list[int | float],
) -> None:
    with pytest.raises(ValidationError):
        EvalConfig(suite="retrieval", dataset="unused.jsonl", k_values=cutoffs)


@pytest.mark.parametrize("field", ["concurrency", "limit", "repeat"])
@pytest.mark.parametrize("value", [0, -1])
def test_run_options_require_positive_counts_on_load_and_assignment(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        RunOptions.model_validate({field: value})
    options = RunOptions()
    with pytest.raises(ValidationError):
        setattr(options, field, value)


@pytest.mark.parametrize("name", ["retrieval", "generation", "extraction", "hybrid"])
def test_shipped_suite_configurations_remain_valid(name: str) -> None:
    path = Path(__file__).resolve().parents[1] / "configs" / f"{name}.yaml"

    assert load_config(path).suite

"""회귀 게이트.

평가를 리포트로만 두면 아무도 안 보게 된다. 게이트는 기준 미달이나 회귀를
CI 실패로 바꿔서, 품질 저하가 머지되기 전에 드러나게 한다.

- `min` / `max`: 절대 기준. 서비스가 만족해야 할 하한과 상한.
- `max_regression`: 베이스라인 대비 허용 하락폭. 절대 기준을 아직 정하기
  어려운 초기 단계에서 "적어도 나빠지지는 않는다"를 보장한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from linkpaper_eval.config import GateRule
from linkpaper_eval.schemas import RunResult

_LOWER_IS_BETTER = ("error_rate", "latency", "cost")


class GateOutcome(BaseModel):
    metric: str
    passed: bool
    value: float | None
    baseline: float | None = None
    reason: str


class GateReport(BaseModel):
    passed: bool
    outcomes: list[GateOutcome]

    def failures(self) -> list[GateOutcome]:
        return [outcome for outcome in self.outcomes if not outcome.passed]


def load_baseline(path: str | Path | None) -> dict[str, float]:
    if not path:
        return {}
    baseline_path = Path(path)
    if not baseline_path.exists():
        return {}
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    return payload.get("aggregate", payload)


def save_baseline(result: RunResult, path: str | Path) -> Path:
    baseline_path = Path(path)
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "run_id": result.manifest.run_id,
                "suite": result.manifest.suite,
                "target": result.manifest.target,
                "dataset_sha256": result.manifest.dataset_sha256,
                "git_sha": result.manifest.git_sha,
                "aggregate": result.aggregate,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return baseline_path


def evaluate_gates(
    aggregate: dict[str, float],
    rules: dict[str, GateRule],
    baseline: dict[str, float] | None = None,
) -> GateReport:
    baseline = baseline or {}
    outcomes: list[GateOutcome] = []

    for metric, rule in sorted(rules.items()):
        value = aggregate.get(metric)
        if value is None:
            outcomes.append(
                GateOutcome(
                    metric=metric,
                    passed=False,
                    value=None,
                    reason="지표가 이번 실행 결과에 없습니다",
                )
            )
            continue

        reference = baseline.get(metric)
        failures: list[str] = []

        if rule.min is not None and value < rule.min:
            failures.append(f"{value:.4f} < min {rule.min}")
        if rule.max is not None and value > rule.max:
            failures.append(f"{value:.4f} > max {rule.max}")
        if rule.max_regression is not None and reference is not None:
            drop = (
                value - reference
                if _lower_is_better(metric)
                else reference - value
            )
            if drop > rule.max_regression:
                failures.append(
                    f"베이스라인 {reference:.4f} 대비 {drop:.4f} 악화 "
                    f"(허용 {rule.max_regression})"
                )

        outcomes.append(
            GateOutcome(
                metric=metric,
                passed=not failures,
                value=value,
                baseline=reference,
                reason="; ".join(failures) if failures else "통과",
            )
        )

    return GateReport(
        passed=all(outcome.passed for outcome in outcomes),
        outcomes=outcomes,
    )


def _lower_is_better(metric: str) -> bool:
    return any(token in metric for token in _LOWER_IS_BETTER)

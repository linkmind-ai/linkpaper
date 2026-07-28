"""운영 지표.

품질 지표가 좋아져도 p95 지연이 서비스 한계를 넘으면 배포할 수 없으므로
모든 스위트에서 함께 수집한다. 인프라 쪽 용량 산정 근거로도 쓴다.
"""

from __future__ import annotations

from collections.abc import Sequence

from linkpaper_eval.schemas import CaseResult


def percentile(values: Sequence[float], q: float) -> float:
    """선형 보간 백분위수. 표본이 적어도 안정적으로 동작한다."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(results: Sequence[CaseResult]) -> dict[str, float]:
    if not results:
        return {}

    latencies = [result.latency_ms for result in results if result.error is None]
    errors = sum(1 for result in results if result.error is not None)

    summary = {
        "operational.case_count": float(len(results)),
        "operational.error_rate": errors / len(results),
    }
    if latencies:
        summary.update(
            {
                "operational.latency_ms_mean": sum(latencies) / len(latencies),
                "operational.latency_ms_p50": percentile(latencies, 0.50),
                "operational.latency_ms_p95": percentile(latencies, 0.95),
                "operational.latency_ms_max": max(latencies),
            }
        )
    return summary

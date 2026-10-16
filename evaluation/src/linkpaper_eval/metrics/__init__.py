"""평가 지표 모음.

지표 함수는 NaN을 "이 케이스에는 해당 지표를 적용할 수 없음"이라는 뜻으로
사용한다. 집계 시 NaN은 0으로 취급하지 않고 표본에서 제외한다. 정답이 없는
케이스를 0점으로 세면 평균이 조용히 왜곡되기 때문이다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from linkpaper_eval.metrics import extraction, generation, operational, retrieval
from linkpaper_eval.schemas import CaseResult

__all__ = [
    "aggregate",
    "aggregate_by_tag",
    "metric_counts",
    "metric_counts_by_tag",
    "extraction",
    "generation",
    "operational",
    "retrieval",
]


def _mean(values: Iterable[float]) -> float | None:
    usable = [value for value in values if not math.isnan(value)]
    if not usable:
        return None
    return sum(usable) / len(usable)


def aggregate(results: Sequence[CaseResult]) -> dict[str, float]:
    """케이스 지표를 macro average로 집계한다."""
    buckets: dict[str, list[float]] = {}
    for result in results:
        for name, value in result.metrics.items():
            buckets.setdefault(name, []).append(value)

    aggregated: dict[str, float] = {}
    for name, values in sorted(buckets.items()):
        mean = _mean(values)
        if mean is not None:
            aggregated[name] = mean
    aggregated.update(operational.summarize(results))
    return aggregated


def aggregate_by_tag(results: Sequence[CaseResult]) -> dict[str, dict[str, float]]:
    """태그별 집계. 질문 유형별 약점을 찾는 데 사용한다."""
    return {tag: aggregate(items) for tag, items in _group_by_tag(results).items()}


def metric_counts(results: Sequence[CaseResult]) -> dict[str, int]:
    """품질 지표 평균에 실제로 포함된 케이스 수. 운영 지표는 별도 집계다."""
    counts: dict[str, int] = {}
    for result in results:
        for name, value in result.metrics.items():
            if not math.isnan(value):
                counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def metric_counts_by_tag(results: Sequence[CaseResult]) -> dict[str, dict[str, int]]:
    """태그별 품질 지표 표본 수. 한 케이스의 중복 태그는 한 번만 센다."""
    return {tag: metric_counts(items) for tag, items in _group_by_tag(results).items()}


def _group_by_tag(results: Sequence[CaseResult]) -> dict[str, list[CaseResult]]:
    grouped: dict[str, list[CaseResult]] = {}
    for result in results:
        for tag in set(result.tags):
            grouped.setdefault(tag, []).append(result)
    return dict(sorted(grouped.items()))

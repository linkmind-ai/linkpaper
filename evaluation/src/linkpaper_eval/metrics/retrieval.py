"""검색 품질 지표.

모든 함수는 순위가 매겨진 ID 리스트와 정답 집합만 받는다. 저장소(Neo4j,
Elasticsearch)나 검색 방식에 의존하지 않으므로 검색기가 바뀌어도 그대로
쓸 수 있다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    """정답 중 상위 k개 안에 들어온 비율."""
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    hits = gold_set & set(ranked[:k])
    return len(hits) / len(gold_set)


def precision_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    """상위 k개 중 정답 비율. 검색 결과가 k보다 적으면 k로 나눈다."""
    if k <= 0:
        return float("nan")
    gold_set = set(gold)
    hits = sum(1 for chunk_id in ranked[:k] if chunk_id in gold_set)
    return hits / k


def hit_at_k(ranked: Sequence[str], gold: Sequence[str], k: int) -> float:
    """상위 k개 안에 정답이 하나라도 있으면 1."""
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    return 1.0 if gold_set & set(ranked[:k]) else 0.0


def mrr(ranked: Sequence[str], gold: Sequence[str]) -> float:
    """첫 정답 순위의 역수."""
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    for index, chunk_id in enumerate(ranked, start=1):
        if chunk_id in gold_set:
            return 1.0 / index
    return 0.0


def ndcg_at_k(
    ranked: Sequence[str],
    grades: dict[str, int],
    k: int,
) -> float:
    """등급 관련도 기반 nDCG@k.

    `grades`에 없는 ID는 관련도 0으로 본다. 이진 관련도만 있는 데이터셋은
    정답 청크에 1을 넣어 호출하면 된다.
    """
    positives = {key: value for key, value in grades.items() if value > 0}
    if not positives:
        return float("nan")

    dcg = 0.0
    for index, chunk_id in enumerate(ranked[:k], start=1):
        gain = grades.get(chunk_id, 0)
        if gain > 0:
            dcg += (2**gain - 1) / math.log2(index + 1)

    ideal = sorted(positives.values(), reverse=True)[:k]
    idcg = sum(
        (2**gain - 1) / math.log2(index + 1)
        for index, gain in enumerate(ideal, start=1)
    )
    if idcg == 0:
        return float("nan")
    return dcg / idcg


def average_precision(ranked: Sequence[str], gold: Sequence[str]) -> float:
    """MAP 집계를 위한 케이스 단위 AP."""
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    hits = 0
    total = 0.0
    for index, chunk_id in enumerate(ranked, start=1):
        if chunk_id in gold_set:
            hits += 1
            total += hits / index
    return total / len(gold_set)


def routing_correct(expected: str, actual: str) -> float:
    """선택 논문 범위와 글로벌 범위 라우팅이 일치하는지.

    LinkPaper의 핵심 분기인 "선택한 논문만으로 답변 가능한가" 판단을
    직접 측정한다. 기대값이 `unknown`이면 평가에서 제외한다.
    """
    if expected == "unknown":
        return float("nan")
    return 1.0 if expected == actual else 0.0


def evaluate_case(
    ranked: Sequence[str],
    gold: Sequence[str],
    grades: dict[str, int],
    k_values: Sequence[int],
    prefix: str = "retrieval",
) -> dict[str, float]:
    """케이스 하나의 검색 지표 묶음."""
    metrics: dict[str, float] = {}
    for k in k_values:
        metrics[f"{prefix}.recall@{k}"] = recall_at_k(ranked, gold, k)
        metrics[f"{prefix}.precision@{k}"] = precision_at_k(ranked, gold, k)
        metrics[f"{prefix}.hit@{k}"] = hit_at_k(ranked, gold, k)
        metrics[f"{prefix}.ndcg@{k}"] = ndcg_at_k(ranked, grades, k)
    metrics[f"{prefix}.mrr"] = mrr(ranked, gold)
    metrics[f"{prefix}.ap"] = average_precision(ranked, gold)
    return metrics

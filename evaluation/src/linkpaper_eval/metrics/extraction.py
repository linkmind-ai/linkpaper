"""지식그래프 추출 정확도 지표.

neo4j-schema.md 6.2절의 관계 allowlist를 기준으로 추출된 트리플을
정답 트리플과 비교한다. 엄격 일치 외에 술어만 일치하는 완화 일치를 함께
측정해서, 엔티티 정규화 문제와 관계 분류 문제를 구분할 수 있게 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from linkpaper_eval.schemas import Triple


def _prf(true_positive: int, predicted: int, actual: int) -> tuple[float, float, float]:
    precision = true_positive / predicted if predicted else float("nan")
    recall = true_positive / actual if actual else float("nan")
    if not predicted or not actual or precision + recall == 0:
        f1 = 0.0 if (predicted and actual) else float("nan")
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def strict_match(predicted: Sequence[Triple], gold: Sequence[Triple]) -> int:
    """주어·술어·목적어가 모두 일치하는 트리플 수."""
    gold_keys = [triple.key() for triple in gold]
    remaining = list(gold_keys)
    matched = 0
    for triple in predicted:
        key = triple.key()
        if key in remaining:
            remaining.remove(key)
            matched += 1
    return matched


def relaxed_match(predicted: Sequence[Triple], gold: Sequence[Triple]) -> int:
    """주어와 목적어 쌍이 일치하면 술어가 달라도 맞은 것으로 센다.

    엄격 점수와의 차이가 크면 엔티티는 잘 잡지만 관계 타입을 혼동한다는
    뜻이므로, 프롬프트에서 allowlist 정의를 다듬을 신호가 된다.
    """
    remaining = [(triple.key()[0], triple.key()[2]) for triple in gold]
    matched = 0
    for triple in predicted:
        key = (triple.key()[0], triple.key()[2])
        if key in remaining:
            remaining.remove(key)
            matched += 1
    return matched


def entity_coverage(predicted: Sequence[Triple], gold: Sequence[Triple]) -> float:
    """정답에 등장하는 엔티티 중 추출 결과에도 등장한 비율."""
    gold_entities = set()
    for triple in gold:
        subject, _, obj = triple.key()
        gold_entities.update({subject, obj})
    if not gold_entities:
        return float("nan")

    predicted_entities = set()
    for triple in predicted:
        subject, _, obj = triple.key()
        predicted_entities.update({subject, obj})
    return len(gold_entities & predicted_entities) / len(gold_entities)


def evidence_attachment_rate(predicted: Sequence[Triple]) -> float:
    """근거 청크 ID가 붙은 트리플 비율.

    스키마상 LLM 추출 관계는 `chunkId`와 `confidence`를 반드시 가져야 하므로
    이 값이 1보다 작으면 적재 단계에서 스키마 위반이 발생한다.
    """
    if not predicted:
        return float("nan")
    attached = sum(1 for triple in predicted if triple.chunk_id)
    return attached / len(predicted)


def evaluate_case(
    predicted: Sequence[Triple],
    gold: Sequence[Triple],
    prefix: str = "extraction",
) -> dict[str, float]:
    strict = strict_match(predicted, gold)
    relaxed = relaxed_match(predicted, gold)

    strict_p, strict_r, strict_f1 = _prf(strict, len(predicted), len(gold))
    relaxed_p, relaxed_r, relaxed_f1 = _prf(relaxed, len(predicted), len(gold))

    return {
        f"{prefix}.triple_precision": strict_p,
        f"{prefix}.triple_recall": strict_r,
        f"{prefix}.triple_f1": strict_f1,
        f"{prefix}.relaxed_precision": relaxed_p,
        f"{prefix}.relaxed_recall": relaxed_r,
        f"{prefix}.relaxed_f1": relaxed_f1,
        f"{prefix}.entity_coverage": entity_coverage(predicted, gold),
        f"{prefix}.evidence_attachment": evidence_attachment_rate(predicted),
    }

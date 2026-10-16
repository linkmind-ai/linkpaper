"""생성 품질 지표.

근거 충실도(groundedness)와 인용 정확도는 GraphRAG 서비스의 신뢰성을
좌우하므로 LLM 심판 없이도 계산되는 결정적 지표를 함께 둔다. CI에서는
결정적 지표만으로 회귀를 감지하고, LLM 심판은 주기적 평가에서 사용한다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from linkpaper_eval.schemas import EvalCase, TargetResponse

_TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]+")

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "by", "with", "that", "this", "it", "as", "at", "from",
    "이", "그", "저", "것", "수", "등", "및", "를", "을", "은", "는", "에", "의",
}


def tokenize(text: str) -> list[str]:
    """영문 소문자 토큰과 한글 어절을 함께 뽑는 가벼운 토크나이저."""
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


def _answer_tokens(text: str) -> list[str]:
    """검색용 토큰과 달리 숫자·한 글자 정답을 보존한다.

    문장의 불용어는 기존처럼 제외하되, 답 전체가 불용어인 경우에는
    원래 토큰을 사용한다. 따라서 선택지 ``A`` 같은 정답도 비교할 수 있다.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    content_tokens = [token for token in tokens if token not in _STOPWORDS]
    return content_tokens or tokens


def token_f1(prediction: str, reference: str) -> float:
    """중복 토큰 수를 반영하는 F1.

    비교할 정답 토큰이 없으면 미라벨 케이스로 보고 NaN을 반환한다.
    정답이 있는데 예측이 비어 있으면 실패이므로 0점으로 집계한다.
    """
    pred_tokens = _answer_tokens(prediction)
    ref_tokens = _answer_tokens(reference)
    if not ref_tokens:
        return float("nan")
    if not pred_tokens:
        return 0.0

    common: dict[str, int] = {}
    ref_counts: dict[str, int] = {}
    for token in ref_tokens:
        ref_counts[token] = ref_counts.get(token, 0) + 1
    for token in pred_tokens:
        if ref_counts.get(token, 0) > 0:
            ref_counts[token] -= 1
            common[token] = common.get(token, 0) + 1

    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def lexical_groundedness(answer: str, evidence: str) -> float:
    """답변 토큰 중 근거 텍스트에 존재하는 비율.

    환각의 상한을 재는 저비용 대리 지표다. 낮으면 근거 밖 내용을 말하고
    있다는 신호이며, 높다고 해서 논리적으로 옳다는 뜻은 아니다.
    """
    answer_tokens = tokenize(answer)
    if not answer_tokens:
        return float("nan")
    evidence_tokens = set(tokenize(evidence))
    if not evidence_tokens:
        return 0.0
    supported = sum(1 for token in answer_tokens if token in evidence_tokens)
    return supported / len(answer_tokens)


def citation_validity(citations: Sequence[str], retrieved: Sequence[str]) -> float:
    """고유 인용 청크 ID 중 실제 검색 결과 안에 있는 비율.

    존재하지 않는 chunkId를 인용하면 프런트엔드에서 근거 링크가 깨진다.
    인용 자체가 없으면 검증할 대상이 없으므로 NaN이다.
    """
    citation_set = set(citations)
    if not citation_set:
        return float("nan")
    retrieved_set = set(retrieved)
    return len(citation_set & retrieved_set) / len(citation_set)


def citation_precision(citations: Sequence[str], gold: Sequence[str]) -> float:
    """고유 인용 중 정답 청크의 비율. 미라벨은 NaN, 인용 누락은 0점."""
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    citation_set = set(citations)
    if not citation_set:
        return 0.0
    return len(citation_set & gold_set) / len(citation_set)


def citation_recall(citations: Sequence[str], gold: Sequence[str]) -> float:
    gold_set = set(gold)
    if not gold_set:
        return float("nan")
    return len(gold_set & set(citations)) / len(gold_set)


def must_include_rate(answer: str, required: Sequence[str]) -> float:
    """반드시 언급되어야 하는 핵심 표현의 포함률."""
    if not required:
        return float("nan")
    lowered = answer.lower()
    hits = sum(1 for phrase in required if phrase.lower() in lowered)
    return hits / len(required)


def evaluate_case(
    case: EvalCase,
    response: TargetResponse,
    prefix: str = "generation",
) -> dict[str, float]:
    """케이스 하나의 생성 지표 묶음. LLM 심판 점수는 runner에서 합친다."""
    evidence = response.evidence_text()
    retrieved_ids = response.ranked_chunk_ids()
    gold_ids = case.graded_ids()

    metrics = {
        f"{prefix}.groundedness_lexical": lexical_groundedness(
            response.answer, evidence
        ),
        f"{prefix}.citation_validity": citation_validity(
            response.citations, retrieved_ids
        ),
        f"{prefix}.citation_precision": citation_precision(
            response.citations, gold_ids
        ),
        f"{prefix}.citation_recall": citation_recall(
            response.citations, gold_ids
        ),
        f"{prefix}.has_citation": 1.0 if response.citations else 0.0,
        f"{prefix}.must_include": must_include_rate(
            response.answer, case.must_include
        ),
    }
    if case.gold_answer:
        metrics[f"{prefix}.answer_token_f1"] = token_f1(
            response.answer, case.gold_answer
        )
    return metrics

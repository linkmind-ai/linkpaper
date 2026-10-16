"""생성 실패의 평균 제외와 반복 인용에 의한 점수 왜곡을 방지한다."""

from __future__ import annotations

import math

import pytest

from linkpaper_eval.metrics import generation
from linkpaper_eval.schemas import EvalCase, TargetResponse


@pytest.mark.parametrize("prediction", ["", "   ", "...!?"])
def test_missing_answer_scores_zero_when_reference_is_labeled(prediction: str) -> None:
    assert generation.token_f1(prediction, "attention") == 0.0


@pytest.mark.parametrize("reference", ["", "   ", "...!?"])
@pytest.mark.parametrize("prediction", ["", "attention"])
def test_unlabeled_answer_is_not_applicable(prediction: str, reference: str) -> None:
    assert math.isnan(generation.token_f1(prediction, reference))


@pytest.mark.parametrize("answer", ["7", "0", "x", "A", "값", "이", "it"])
def test_short_answers_are_scored(answer: str) -> None:
    assert generation.token_f1(answer, answer) == 1.0
    assert generation.token_f1("", answer) == 0.0
    assert generation.token_f1("unrelated", answer) == 0.0


def test_answer_f1_counts_repeated_tokens_and_keeps_numeric_answers() -> None:
    assert generation.token_f1("7 7 8", "7 8") == pytest.approx(0.8)
    assert generation.token_f1("7", "8") == 0.0


def test_answer_normalization_does_not_change_retrieval_tokenization() -> None:
    assert generation.tokenize("A x 7 이 and attention") == ["attention"]
    assert generation.token_f1("The Transformer uses attention.", "Transformer uses attention") == 1.0


@pytest.mark.parametrize(
    "citations",
    [
        ["gold", "invalid"],
        ["gold", "gold", "gold", "invalid"],
        ["gold", "invalid", "invalid", "invalid"],
    ],
)
def test_repeated_citations_do_not_change_validity_or_precision(citations: list[str]) -> None:
    assert generation.citation_validity(citations, ["gold", "gold"]) == 0.5
    assert generation.citation_precision(citations, ["gold", "gold"]) == 0.5
    assert generation.citation_recall(citations, ["gold", "gold"]) == 1.0


def test_missing_citations_are_penalized_when_gold_is_available() -> None:
    assert generation.citation_precision([], ["gold"]) == 0.0
    assert generation.citation_recall([], ["gold"]) == 0.0
    assert math.isnan(generation.citation_validity([], ["gold"]))


@pytest.mark.parametrize("citations", [[], ["predicted"]])
def test_unlabeled_citation_metrics_are_not_applicable(citations: list[str]) -> None:
    assert math.isnan(generation.citation_precision(citations, []))
    assert math.isnan(generation.citation_recall(citations, []))


def test_case_evaluation_includes_empty_predictions_as_failures() -> None:
    case = EvalCase(case_id="missing", question="How many?", gold_answer="7", gold_chunk_ids=["gold"])
    metrics = generation.evaluate_case(case, TargetResponse())
    assert metrics["generation.answer_token_f1"] == 0.0
    assert metrics["generation.citation_precision"] == 0.0
    assert metrics["generation.citation_recall"] == 0.0
    assert metrics["generation.has_citation"] == 0.0


def test_case_evaluation_does_not_score_missing_answer_labels() -> None:
    case = EvalCase(case_id="unlabeled", question="How many?")
    metrics = generation.evaluate_case(case, TargetResponse(answer="7", citations=["predicted"]))
    assert "generation.answer_token_f1" not in metrics
    assert math.isnan(metrics["generation.citation_precision"])
    assert math.isnan(metrics["generation.citation_recall"])


def test_citation_scores_include_positive_grade_only_labels() -> None:
    case = EvalCase(case_id="graded", question="Why?", grades={"relevant": 2})
    metrics = generation.evaluate_case(case, TargetResponse(citations=["relevant"]))
    assert metrics["generation.citation_precision"] == 1.0
    assert metrics["generation.citation_recall"] == 1.0


def test_explicit_zero_grade_overrides_citation_gold_ids() -> None:
    case = EvalCase(
        case_id="graded",
        question="Why?",
        gold_chunk_ids=["irrelevant", "relevant"],
        grades={"irrelevant": 0},
    )
    metrics = generation.evaluate_case(case, TargetResponse(citations=["irrelevant"]))
    assert metrics["generation.citation_precision"] == 0.0
    assert metrics["generation.citation_recall"] == 0.0

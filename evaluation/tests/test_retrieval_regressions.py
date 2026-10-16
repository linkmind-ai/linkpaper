"""중복 검색 결과와 평가 불가 입력에 대한 검색 지표 회귀 테스트."""

from __future__ import annotations

import math
from itertools import product

import pytest

from linkpaper_eval.metrics import retrieval


def test_duplicate_relevant_ids_do_not_earn_repeated_credit() -> None:
    ranked = ["a", "a", "b"]
    gold = ["a", "b"]
    grades = {"a": 3, "b": 1}

    assert retrieval.precision_at_k(ranked, gold, 2) == pytest.approx(1 / 2)
    assert retrieval.precision_at_k(ranked, gold, 3) == pytest.approx(2 / 3)
    assert retrieval.recall_at_k(ranked, gold, 2) == pytest.approx(1 / 2)
    assert retrieval.recall_at_k(ranked, gold, 3) == 1.0
    assert retrieval.average_precision(ranked, gold) == pytest.approx((1 + 2 / 3) / 2)
    # The duplicate occupies rank 2, so b's gain is discounted at rank 3.
    assert retrieval.ndcg_at_k(ranked, grades, 3) == pytest.approx(
        (7 + 1 / math.log2(4)) / (7 + 1 / math.log2(3))
    )


def test_duplicate_irrelevant_ids_preserve_rank_positions() -> None:
    ranked = ["irrelevant", "irrelevant", "a"]

    assert retrieval.hit_at_k(ranked, ["a"], 2) == 0.0
    assert retrieval.mrr(ranked, ["a"]) == pytest.approx(1 / 3)
    assert retrieval.average_precision(ranked, ["a"]) == pytest.approx(1 / 3)
    assert retrieval.ndcg_at_k(ranked, {"a": 1}, 3) == pytest.approx(1 / 2)


def test_duplicate_gold_ids_do_not_change_scores() -> None:
    ranked = ["a", "irrelevant", "b"]
    grades = {"a": 1, "b": 1}

    assert retrieval.evaluate_case(ranked, ["a", "b", "a"], grades, [1, 3]) == (
        retrieval.evaluate_case(ranked, ["a", "b"], grades, [1, 3])
    )


@pytest.mark.parametrize("k", [0, -1, -5])
def test_nonpositive_cutoffs_are_not_applicable(k: int) -> None:
    scores = retrieval.evaluate_case(["a", "b"], ["a"], {"a": 1}, [k])

    for metric in ("recall", "precision", "hit", "ndcg"):
        assert math.isnan(scores[f"retrieval.{metric}@{k}"])
    assert scores["retrieval.mrr"] == 1.0
    assert scores["retrieval.ap"] == 1.0


@pytest.mark.parametrize("ranked", [[], ["a"]])
def test_missing_gold_is_not_applicable_for_every_retrieval_metric(
    ranked: list[str],
) -> None:
    scores = retrieval.evaluate_case(ranked, [], {}, [1, 3])

    assert all(math.isnan(score) for score in scores.values())


def test_empty_ranking_with_known_gold_is_a_miss() -> None:
    scores = retrieval.evaluate_case([], ["a"], {"a": 1}, [1, 3])

    assert all(score == 0.0 for score in scores.values())


def test_nonpositive_grades_are_not_relevant() -> None:
    assert math.isnan(retrieval.ndcg_at_k(["a", "b"], {"a": 0, "b": -1}, 2))
    assert retrieval.ndcg_at_k(
        ["a", "b", "c"], {"a": 0, "b": -1, "c": 2}, 3
    ) == pytest.approx(1 / 2)


def test_scores_remain_bounded_for_rankings_with_repeated_ids() -> None:
    # Cover all short rankings, including repeated relevant and irrelevant IDs.
    for length in range(5):
        for ranked in product(["a", "b", "irrelevant"], repeat=length):
            scores = retrieval.evaluate_case(
                ranked, ["a", "b"], {"a": 3, "b": 1}, [1, 2, 5]
            )
            assert all(0 <= score <= 1 for score in scores.values()), ranked

"""지표 함수 단위 테스트.

지표가 틀리면 잘못된 방향으로 파이프라인을 튜닝하게 되므로, 손으로 계산할
수 있는 최소 사례로 고정한다.
"""

from __future__ import annotations

import math

import pytest

from linkpaper_eval.metrics import extraction, generation, operational, retrieval
from linkpaper_eval.schemas import CaseResult, Triple


class TestRetrieval:
    def test_recall_counts_only_gold_within_k(self) -> None:
        ranked = ["c1", "c2", "c3", "c4"]
        gold = ["c1", "c4"]
        assert retrieval.recall_at_k(ranked, gold, 3) == 0.5
        assert retrieval.recall_at_k(ranked, gold, 4) == 1.0

    def test_precision_divides_by_k_not_result_count(self) -> None:
        assert retrieval.precision_at_k(["c1"], ["c1"], 5) == pytest.approx(0.2)

    def test_mrr_uses_first_hit(self) -> None:
        assert retrieval.mrr(["x", "y", "c1"], ["c1"]) == pytest.approx(1 / 3)
        assert retrieval.mrr(["x", "y"], ["c1"]) == 0.0

    def test_ndcg_is_one_for_ideal_ranking(self) -> None:
        grades = {"c1": 3, "c2": 1}
        assert retrieval.ndcg_at_k(["c1", "c2"], grades, 2) == pytest.approx(1.0)

    def test_ndcg_penalizes_swapped_order(self) -> None:
        grades = {"c1": 3, "c2": 1}
        swapped = retrieval.ndcg_at_k(["c2", "c1"], grades, 2)
        assert 0 < swapped < 1

    def test_empty_gold_is_not_applicable(self) -> None:
        assert math.isnan(retrieval.recall_at_k(["c1"], [], 5))

    def test_routing_accuracy(self) -> None:
        assert retrieval.routing_correct("global", "global") == 1.0
        assert retrieval.routing_correct("global", "selected") == 0.0
        assert math.isnan(retrieval.routing_correct("unknown", "selected"))


class TestGeneration:
    def test_groundedness_detects_unsupported_answer(self) -> None:
        # 어간 추출을 하지 않으므로 improves/improve 같은 굴절형은 감점된다.
        # 절대값이 아니라 근거 있는 답변과 없는 답변의 격차를 보는 지표다.
        grounded = generation.lexical_groundedness(
            "multi-head attention improves quality",
            "The model uses multi-head attention to improve quality.",
        )
        ungrounded = generation.lexical_groundedness(
            "quantum entanglement drives protein folding",
            "The model uses multi-head attention to improve quality.",
        )
        assert grounded >= 0.8
        assert ungrounded < 0.2
        assert grounded - ungrounded > 0.6

    def test_citation_validity_flags_hallucinated_ids(self) -> None:
        assert generation.citation_validity(["a", "b"], ["a", "c"]) == 0.5
        assert generation.citation_validity(["a"], ["a"]) == 1.0

    def test_token_f1_ignores_stopwords(self) -> None:
        score = generation.token_f1(
            "The Transformer uses attention.", "Transformer uses attention"
        )
        assert score == pytest.approx(1.0)

    def test_must_include_rate(self) -> None:
        rate = generation.must_include_rate("uses GLUE and SQuAD", ["glue", "squad"])
        assert rate == 1.0


class TestExtraction:
    def test_strict_and_relaxed_matching_differ_on_predicate(self) -> None:
        gold = [Triple(subject="model:bert", predicate="BASED_ON", object="model:transformer")]
        predicted = [
            Triple(subject="model:bert", predicate="EXTENDS", object="model:transformer")
        ]
        scores = extraction.evaluate_case(predicted, gold)
        assert scores["extraction.triple_f1"] == 0.0
        assert scores["extraction.relaxed_f1"] == pytest.approx(1.0)

    def test_normalization_tolerates_case_and_spacing(self) -> None:
        gold = [Triple(subject="Model:BERT", predicate="based_on", object="model:transformer")]
        predicted = [
            Triple(subject="model:bert", predicate="BASED ON", object="Model:Transformer")
        ]
        assert extraction.strict_match(predicted, gold) == 1

    def test_evidence_attachment_requires_chunk_id(self) -> None:
        predicted = [
            Triple(subject="a", predicate="P", object="b", chunk_id="c1"),
            Triple(subject="a", predicate="P", object="c"),
        ]
        assert extraction.evidence_attachment_rate(predicted) == 0.5


class TestOperational:
    def test_percentile_interpolates(self) -> None:
        assert operational.percentile([10, 20, 30], 0.5) == pytest.approx(20)

    def test_error_rate_counts_failed_cases(self) -> None:
        results = [
            CaseResult(case_id="a", question="q", latency_ms=10),
            CaseResult(case_id="b", question="q", latency_ms=0, error="http_501"),
        ]
        summary = operational.summarize(results)
        assert summary["operational.error_rate"] == 0.5
        assert summary["operational.latency_ms_p50"] == pytest.approx(10)

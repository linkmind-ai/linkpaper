"""BM25 렉시컬 베이스라인 타깃.

두 가지 목적이 있다.

1. 백엔드 구현 전에도 평가 파이프라인 전체를 실행하고 검증할 수 있다.
2. GraphRAG가 반드시 넘어야 할 하한선을 제공한다. 그래프 확장과 벡터
   검색을 붙였는데 단순 BM25보다 나쁘면 파이프라인에 문제가 있는 것이다.

외부 의존성 없이 순수 파이썬으로 구현해서 CI에서 API 키 없이 돌아간다.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from pathlib import Path

from linkpaper_eval.metrics.generation import tokenize
from linkpaper_eval.schemas import (
    EvalCase,
    RetrievedItem,
    TargetResponse,
    Triple,
)
from linkpaper_eval.targets.base import EvalTarget

_K1 = 1.5
_B = 0.75


class LexicalBaselineTarget(EvalTarget):
    """고정된 코퍼스 위에서 BM25 검색과 추출 요약을 수행한다."""

    name = "lexical_baseline"

    def __init__(
        self,
        corpus: str,
        top_k: int = 10,
        citation_count: int = 3,
        routing_threshold: float = 0.45,
        answer_sentences: int = 2,
    ) -> None:
        self.corpus_path = Path(corpus)
        self.top_k = top_k
        self.citation_count = citation_count
        self.routing_threshold = routing_threshold
        self.answer_sentences = answer_sentences

        self.documents = self._load_corpus(self.corpus_path)
        self._build_index()

    @staticmethod
    def _load_corpus(path: Path) -> list[dict]:
        if not path.exists():
            raise FileNotFoundError(f"Corpus not found: {path}")
        documents = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    documents.append(json.loads(line))
        if not documents:
            raise ValueError(f"Corpus is empty: {path}")
        return documents

    def _build_index(self) -> None:
        self.doc_tokens = [tokenize(doc.get("text", "")) for doc in self.documents]
        self.doc_lengths = [len(tokens) for tokens in self.doc_tokens]
        self.avg_length = sum(self.doc_lengths) / len(self.doc_lengths) or 1.0

        document_frequency: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            document_frequency.update(set(tokens))

        total = len(self.documents)
        self.idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }
        self.term_frequency = [Counter(tokens) for tokens in self.doc_tokens]

    def _score(self, query_tokens: list[str], index: int) -> float:
        score = 0.0
        length = self.doc_lengths[index] or 1
        frequencies = self.term_frequency[index]
        for term in query_tokens:
            frequency = frequencies.get(term, 0)
            if frequency == 0:
                continue
            idf = self.idf.get(term, 0.0)
            denominator = frequency + _K1 * (
                1 - _B + _B * length / self.avg_length
            )
            score += idf * (frequency * (_K1 + 1)) / denominator
        return score

    def run(self, case: EvalCase) -> TargetResponse:
        started = time.perf_counter()
        query_tokens = tokenize(case.question)

        scored: list[tuple[float, int]] = []
        for index in range(len(self.documents)):
            score = self._score(query_tokens, index)
            if score > 0:
                scored.append((score, index))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))

        # 선택 논문 안에서 충분히 강한 근거가 나오면 selected, 아니면 global.
        # 백엔드의 조건부 라우팅과 같은 판단을 단순 규칙으로 흉내 낸다.
        best_overall = scored[0][0] if scored else 0.0
        best_selected = 0.0
        for score, index in scored:
            if self.documents[index].get("paper_id") == case.paper_id:
                best_selected = score
                break
        ratio = best_selected / best_overall if best_overall else 0.0
        scope = "selected" if ratio >= self.routing_threshold else "global"

        if scope == "selected" and case.paper_id:
            scored = [
                pair
                for pair in scored
                if self.documents[pair[1]].get("paper_id") == case.paper_id
            ]

        retrieved: list[RetrievedItem] = []
        for rank, (score, index) in enumerate(scored[: self.top_k], start=1):
            document = self.documents[index]
            retrieved.append(
                RetrievedItem(
                    chunk_id=document["chunk_id"],
                    paper_id=document.get("paper_id"),
                    text=document.get("text", ""),
                    scope=scope,
                    retrieval_source="lexical_baseline",
                    rank=rank,
                    score=round(score, 4),
                    section=document.get("section"),
                )
            )

        citations = [item.chunk_id for item in retrieved[: self.citation_count]]
        answer = self._extractive_answer(retrieved)
        triples = self._collect_triples(retrieved)

        elapsed = (time.perf_counter() - started) * 1000
        return TargetResponse(
            answer=answer,
            citations=citations,
            retrieved=retrieved,
            scope=scope,
            triples=triples,
            latency_ms=round(elapsed, 3),
        )

    def _extractive_answer(self, retrieved: list[RetrievedItem]) -> str:
        """상위 근거의 첫 문장들을 이어 붙인 추출식 답변."""
        sentences: list[str] = []
        for item in retrieved[: self.answer_sentences]:
            first = item.text.split(". ")[0].strip()
            if first:
                sentences.append(first if first.endswith(".") else f"{first}.")
        return " ".join(sentences)

    def _collect_triples(self, retrieved: list[RetrievedItem]) -> list[Triple]:
        """코퍼스에 미리 붙여 둔 트리플을 근거 청크 기준으로 회수한다."""
        by_chunk = {
            document["chunk_id"]: document.get("triples", [])
            for document in self.documents
        }
        triples: list[Triple] = []
        for item in retrieved[: self.citation_count]:
            for raw in by_chunk.get(item.chunk_id, []):
                triples.append(
                    Triple(
                        subject=raw["subject"],
                        predicate=raw["predicate"],
                        object=raw["object"],
                        chunk_id=item.chunk_id,
                        confidence=raw.get("confidence", 0.7),
                    )
                )
        return triples

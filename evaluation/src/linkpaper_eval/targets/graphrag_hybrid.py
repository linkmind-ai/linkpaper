"""Qdrant 벡터 검색 + Neo4j 그래프 확장 타깃.

백엔드 API를 거치지 않고 저장소에 직접 붙어서 검색만 평가한다. 백엔드가
아직 501을 반환하는 동안에도 "인덱스와 그래프가 실제로 답을 찾아 주는가"를
잴 수 있다는 것이 이 타깃의 존재 이유다. 백엔드가 완성되면 `--target http`와
나란히 비교해서, 점수 차이가 검색 때문인지 생성 때문인지 가를 수 있다.

동작은 data-retrieval-architecture.md의 조건부 확장을 단순화한 형태다.

1. 질문을 임베딩한다.
2. 선택 논문 안에서 검색하고, 코퍼스 전체에서도 검색한다.
3. 두 최고 점수의 비율로 범위를 정한다. 선택 논문 근거가 충분히 강하면
   `selected`, 아니면 `global`. BM25 베이스라인과 같은 판정 규칙을 써서
   두 타깃의 `routing.accuracy`를 직접 비교할 수 있게 했다.
4. `global`이면 Neo4j 인용 관계로 이웃 논문을 찾아 후보를 넓힌다.
5. 상위 근거의 첫 문장들로 추출식 답변을 만든다.

답변 생성에 LLM을 쓰지 않는 것은 의도적이다. 이 타깃이 재는 대상은
검색이고, LLM을 끼우면 생성 품질이 검색 점수에 섞인다. 생성까지 포함한
평가는 백엔드 타깃이 담당한다.
"""

from __future__ import annotations

import time

from linkpaper_eval.schemas import EvalCase, RetrievedItem, TargetResponse
from linkpaper_eval.stores.config import (
    EmbeddingSettings,
    Neo4jSettings,
    QdrantSettings,
)
from linkpaper_eval.stores.embedding import build_embedder
from linkpaper_eval.targets.base import EvalTarget


class GraphRagHybridTarget(EvalTarget):
    """벡터 인덱스와 지식그래프를 함께 쓰는 검색 타깃."""

    name = "graphrag_hybrid"

    def __init__(
        self,
        top_k: int = 10,
        citation_count: int = 3,
        routing_threshold: float = 0.45,
        answer_sentences: int = 2,
        graph_expansion: bool = True,
        graph_hops: int = 1,
        expansion_papers: int = 5,
        expansion_chunks_per_paper: int = 3,
        qdrant: dict | None = None,
        neo4j: dict | None = None,
        embedding: dict | None = None,
    ) -> None:
        from linkpaper_eval.stores.qdrant_store import QdrantStore

        self.top_k = top_k
        self.citation_count = citation_count
        self.routing_threshold = routing_threshold
        self.answer_sentences = answer_sentences
        self.graph_expansion = graph_expansion
        self.graph_hops = graph_hops
        self.expansion_papers = expansion_papers
        self.expansion_chunks_per_paper = expansion_chunks_per_paper

        self.qdrant = QdrantStore(QdrantSettings.from_env(**(qdrant or {})))
        self.embedder = build_embedder(
            EmbeddingSettings.from_env(**(embedding or {}))
        )
        self._neo4j = None
        if graph_expansion:
            from linkpaper_eval.stores.neo4j_store import Neo4jStore

            self._neo4j = Neo4jStore(Neo4jSettings.from_env(**(neo4j or {})))

    def run(self, case: EvalCase) -> TargetResponse:
        started = time.perf_counter()
        vector = self.embedder.embed_query(case.question)

        global_hits = self.qdrant.search(vector, top_k=self.top_k)
        selected_hits = (
            self.qdrant.search(vector, top_k=self.top_k, paper_ids=[case.paper_id])
            if case.paper_id
            else []
        )

        best_global = global_hits[0].score if global_hits else 0.0
        best_selected = selected_hits[0].score if selected_hits else 0.0
        ratio = best_selected / best_global if best_global else 0.0
        scope = "selected" if ratio >= self.routing_threshold else "global"

        if scope == "selected" and selected_hits:
            hits = selected_hits
        else:
            hits = list(global_hits)
            if self.graph_expansion and self._neo4j is not None:
                hits.extend(self._expand(case, hits, vector))

        # 같은 청크가 벡터 검색과 그래프 확장에서 모두 나올 수 있다.
        deduped = []
        seen: set[str] = set()
        for hit in hits:
            if hit.chunk.chunk_id in seen:
                continue
            seen.add(hit.chunk.chunk_id)
            deduped.append(hit)
        deduped.sort(key=lambda hit: -hit.score)

        retrieved = [
            RetrievedItem(
                chunk_id=hit.chunk.chunk_id,
                paper_id=hit.chunk.paper_id,
                text=hit.chunk.text,
                scope=scope,
                retrieval_source=(
                    "neo4j_graph"
                    if hit.rank is None
                    else "qdrant_vector"
                ),
                rank=rank,
                score=round(hit.score, 4),
                section=hit.chunk.section,
            )
            for rank, hit in enumerate(deduped[: self.top_k], start=1)
        ]

        elapsed = (time.perf_counter() - started) * 1000
        return TargetResponse(
            answer=self._extractive_answer(retrieved),
            citations=[item.chunk_id for item in retrieved[: self.citation_count]],
            retrieved=retrieved,
            scope=scope,
            latency_ms=round(elapsed, 3),
        )

    def _expand(self, case: EvalCase, hits: list, vector: list[float]) -> list:
        """인용 관계로 이웃 논문의 청크를 후보에 더한다."""
        from linkpaper_eval.stores.records import SearchHit

        seed_papers = [case.paper_id] if case.paper_id else []
        seed_papers += [hit.chunk.paper_id for hit in hits[:3] if hit.chunk.paper_id]
        seed_papers = list(dict.fromkeys(filter(None, seed_papers)))
        if not seed_papers:
            return []

        try:
            related = self._neo4j.related_papers(
                seed_papers, hops=self.graph_hops, limit=self.expansion_papers
            )
            chunks = self._neo4j.chunks_for_papers(
                related, limit_per_paper=self.expansion_chunks_per_paper
            )
        except Exception:  # noqa: BLE001 - 그래프 실패로 검색 전체를 버리지 않는다
            return []

        # 그래프로 데려온 청크는 벡터 점수가 없으므로 질의와의 유사도를
        # 직접 계산해 같은 척도에 올린다. 그래야 벡터 결과와 함께 정렬된다.
        if not chunks:
            return []
        vectors = self.embedder.embed([chunk.text for chunk in chunks])
        expanded = []
        for chunk, chunk_vector in zip(chunks, vectors):
            score = sum(a * b for a, b in zip(vector, chunk_vector))
            expanded.append(SearchHit(chunk=chunk, score=float(score), rank=None))
        return expanded

    def _extractive_answer(self, retrieved: list[RetrievedItem]) -> str:
        sentences: list[str] = []
        for item in retrieved[: self.answer_sentences]:
            first = item.text.split(". ")[0].strip()
            if first:
                sentences.append(first if first.endswith(".") else f"{first}.")
        return " ".join(sentences)

    def close(self) -> None:
        self.qdrant.close()
        self.embedder.close()
        if self._neo4j is not None:
            self._neo4j.close()

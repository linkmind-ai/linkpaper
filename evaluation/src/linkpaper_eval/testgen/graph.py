"""청크 그래프.

평가셋 생성의 품질은 "어떤 청크 쌍을 묶어서 질문을 만드는가"에서 갈린다.
임의의 두 청크를 묶으면 답이 존재하지 않는 질문이 나온다. 그래서 근거가
되는 연결만 사용한다. 연결의 출처는 두 가지다.

- **그래프 인덱스(Neo4j)** — 인용(`CITES`), 같은 논문(`NEXT_CHUNK`),
  공유 엔티티(`MENTIONS`). 논문 사이의 관계가 명시적이므로 "이 논문의
  한계를 해결한 후속 연구는?" 같은 질문의 정답 근거를 만들 수 있다.
- **벡터 인덱스(Qdrant)** — 의미적으로 가까운 청크. 인용 관계가 없어도
  같은 주제를 다루는 논문을 이어 준다.

두 출처를 합친 결과가 `ChunkGraph`다. 오프라인 생성기와 ragas 생성기가
모두 이 구조를 입력으로 받는다.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.stores.config import StoreSettings
from linkpaper_eval.stores.embedding import Embedder, build_embedder
from linkpaper_eval.stores.records import ChunkRecord

# 그래프 간선 종류. 멀티홉 질문의 성격을 태그로 남길 때 그대로 쓴다.
GRAPH_LINK_TYPES = ("next", "same_paper", "cites", "shared_entity")
VECTOR_LINK_TYPE = "vector"


class ChunkLink(BaseModel):
    source: str
    target: str
    type: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def key(self) -> tuple[str, str, str]:
        return (self.source, self.target, self.type)


class ChunkGraph(BaseModel):
    chunks: list[ChunkRecord] = Field(default_factory=list)
    links: list[ChunkLink] = Field(default_factory=list)

    def index(self) -> dict[str, ChunkRecord]:
        return {chunk.chunk_id: chunk for chunk in self.chunks}

    def paper_of(self, chunk_id: str) -> str | None:
        chunk = self.index().get(chunk_id)
        return chunk.paper_id if chunk else None

    def cross_paper_links(self) -> list[ChunkLink]:
        """서로 다른 논문을 잇는 간선.

        멀티홉 질문의 후보다. 같은 논문 안의 연결로 만든 질문은 결국
        선택 논문만으로 답할 수 있어서 global 질의가 되지 못한다.
        """
        lookup = self.index()
        result: list[ChunkLink] = []
        for link in self.links:
            source = lookup.get(link.source)
            target = lookup.get(link.target)
            if source and target and source.paper_id != target.paper_id:
                result.append(link)
        return result

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for link in self.links:
            counts[link.type] = counts.get(link.type, 0) + 1
        return {
            "chunks": len(self.chunks),
            "papers": len({chunk.paper_id for chunk in self.chunks}),
            "links": len(self.links),
            "links_by_type": counts,
            "cross_paper_links": len(self.cross_paper_links()),
        }


def _dedupe(links: Sequence[ChunkLink]) -> list[ChunkLink]:
    seen: set[tuple[str, str, str]] = set()
    result: list[ChunkLink] = []
    for link in links:
        if link.source == link.target:
            continue
        key = link.key()
        if key in seen:
            continue
        seen.add(key)
        result.append(link)
    return result


def graph_links(
    chunks: Sequence[ChunkRecord],
    settings: StoreSettings | None = None,
    include_same_paper: bool = True,
) -> list[ChunkLink]:
    """Neo4j에서 청크 간 간선을 읽어 온다."""
    from linkpaper_eval.stores.neo4j_store import Neo4jStore

    settings = settings or StoreSettings.from_env()
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    links: list[ChunkLink] = []

    with Neo4jStore(settings.neo4j) as store:
        for edge in store.graph_edges(chunk_ids):
            links.append(
                ChunkLink(
                    source=edge["source"],
                    target=edge["target"],
                    type=edge.get("type", "unknown"),
                    metadata={
                        key: value
                        for key, value in edge.items()
                        if key not in {"source", "target", "type"}
                    },
                )
            )

    if include_same_paper:
        links.extend(same_paper_links(chunks))
    return _dedupe(links)


def same_paper_links(chunks: Sequence[ChunkRecord]) -> list[ChunkLink]:
    """같은 논문의 인접 청크를 잇는다. DB 없이도 만들 수 있는 연결이다."""
    by_paper: dict[str, list[ChunkRecord]] = {}
    for chunk in chunks:
        by_paper.setdefault(chunk.paper_id, []).append(chunk)

    links: list[ChunkLink] = []
    for paper_chunks in by_paper.values():
        ordered = sorted(
            paper_chunks,
            key=lambda chunk: (
                chunk.chunk_index if chunk.chunk_index is not None else 0,
                chunk.chunk_id,
            ),
        )
        for first, second in zip(ordered, ordered[1:]):
            links.append(
                ChunkLink(source=first.chunk_id, target=second.chunk_id, type="next")
            )
    return links


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def vector_links_local(
    chunks: Sequence[ChunkRecord],
    embedder: Embedder | None = None,
    top_k: int = 3,
    min_score: float | None = None,
    cross_paper_only: bool = True,
) -> list[ChunkLink]:
    """메모리에서 코사인 유사도를 계산해 간선을 만든다.

    Qdrant 없이도 벡터 기반 연결을 만들 수 있어야 오프라인에서 파이프라인
    전체를 확인할 수 있다. 청크 수가 수천 개를 넘으면 O(n²)가 부담되므로
    그때는 `vector_links_qdrant`를 쓴다.
    """
    embedder = embedder or build_embedder()
    threshold = embedder.link_threshold if min_score is None else min_score
    vectors = embedder.embed([chunk.text for chunk in chunks])

    links: list[ChunkLink] = []
    for index, chunk in enumerate(chunks):
        scored: list[tuple[float, int]] = []
        for other_index, other in enumerate(chunks):
            if other_index == index:
                continue
            if cross_paper_only and other.paper_id == chunk.paper_id:
                continue
            score = _cosine(vectors[index], vectors[other_index])
            if score >= threshold:
                scored.append((score, other_index))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        for score, other_index in scored[:top_k]:
            links.append(
                ChunkLink(
                    source=chunk.chunk_id,
                    target=chunks[other_index].chunk_id,
                    type=VECTOR_LINK_TYPE,
                    score=round(score, 4),
                )
            )
    return _dedupe(links)


def vector_links_qdrant(
    chunks: Sequence[ChunkRecord],
    settings: StoreSettings | None = None,
    top_k: int = 3,
    min_score: float | None = None,
    cross_paper_only: bool = True,
) -> list[ChunkLink]:
    """Qdrant 벡터 인덱스에서 최근접 이웃을 조회해 간선을 만든다."""
    from linkpaper_eval.stores.qdrant_store import QdrantStore

    settings = settings or StoreSettings.from_env()
    embedder = build_embedder(settings.embedding)
    threshold = embedder.link_threshold if min_score is None else min_score
    try:
        vectors = embedder.embed([chunk.text for chunk in chunks])
    finally:
        embedder.close()

    links: list[ChunkLink] = []
    with QdrantStore(settings.qdrant) as store:
        for chunk, vector in zip(chunks, vectors):
            # 자기 자신이 1위로 나오므로 한 칸 더 받는다.
            hits = store.search(vector, top_k=top_k + 1)
            added = 0
            for hit in hits:
                if hit.chunk.chunk_id == chunk.chunk_id:
                    continue
                if cross_paper_only and hit.chunk.paper_id == chunk.paper_id:
                    continue
                if hit.score < threshold:
                    continue
                links.append(
                    ChunkLink(
                        source=chunk.chunk_id,
                        target=hit.chunk.chunk_id,
                        type=VECTOR_LINK_TYPE,
                        score=round(hit.score, 4),
                    )
                )
                added += 1
                if added >= top_k:
                    break
    return _dedupe(links)


def build_chunk_graph(
    chunks: Sequence[ChunkRecord],
    settings: StoreSettings | None = None,
    use_graph: bool = True,
    use_vector: bool = True,
    vector_backend: str = "auto",
    top_k: int = 3,
    min_score: float | None = None,
) -> ChunkGraph:
    """그래프 간선과 벡터 간선을 합쳐 `ChunkGraph`를 만든다.

    `vector_backend='auto'`는 Qdrant 연결을 먼저 시도하고, 실패하면
    메모리 계산으로 내려간다. DB가 없는 환경에서도 생성이 끊기지 않게
    하려는 것이며, 어느 경로를 썼는지는 실행 로그에 남는다.
    """
    chunks = list(chunks)
    links: list[ChunkLink] = []

    if use_graph:
        try:
            links.extend(graph_links(chunks, settings))
        except Exception:  # noqa: BLE001 - 그래프가 없어도 벡터로 진행한다
            links.extend(same_paper_links(chunks))
    else:
        links.extend(same_paper_links(chunks))

    if use_vector:
        if vector_backend in {"auto", "qdrant"}:
            try:
                links.extend(
                    vector_links_qdrant(
                        chunks, settings, top_k=top_k, min_score=min_score
                    )
                )
            except Exception:  # noqa: BLE001
                if vector_backend == "qdrant":
                    raise
                links.extend(
                    vector_links_local(chunks, top_k=top_k, min_score=min_score)
                )
        else:
            links.extend(
                vector_links_local(chunks, top_k=top_k, min_score=min_score)
            )

    return ChunkGraph(chunks=chunks, links=_dedupe(links))

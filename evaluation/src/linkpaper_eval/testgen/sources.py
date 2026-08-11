"""평가셋 생성의 입력이 되는 청크를 확보한다.

세 가지 소스를 지원한다.

- `neo4j` — 그래프에 적재된 `:Chunk` 노드. 실제 서비스가 검색하는 것과
  같은 데이터라 생성한 평가셋이 곧바로 유효하다.
- `qdrant` — 벡터 컬렉션의 payload. 그래프 없이 벡터 인덱스만 있을 때.
- `jsonl` — 코퍼스 파일. 네트워크나 DB 없이 파이프라인을 확인할 때.

어떤 소스를 쓰든 `list[ChunkRecord]`로 정규화되므로 이후 단계는 소스를
알 필요가 없다.

`paper_ids`로 범위를 좁히면 특정 논문과 그 인용 이웃만으로 평가셋을 만들
수 있다. 코퍼스 전체를 LLM에 통과시키면 비용이 빠르게 커지므로, 기본
사용법은 관심 있는 논문 집합에서 시작해 그래프로 확장하는 것이다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from linkpaper_eval.benchmark.download import read_jsonl
from linkpaper_eval.stores.config import StoreSettings
from linkpaper_eval.stores.records import ChunkRecord


def from_jsonl(path: str | Path, limit: int | None = None) -> list[ChunkRecord]:
    rows = read_jsonl(Path(path))
    chunks = [ChunkRecord.from_payload(row) for row in rows if row.get("text")]
    return chunks[:limit] if limit else chunks


def from_qdrant(
    settings: StoreSettings | None = None, limit: int | None = None
) -> list[ChunkRecord]:
    from linkpaper_eval.stores.qdrant_store import QdrantStore

    settings = settings or StoreSettings.from_env()
    with QdrantStore(settings.qdrant) as store:
        return list(store.iter_chunks(limit=limit))


def from_neo4j(
    settings: StoreSettings | None = None,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    expand_hops: int = 0,
) -> list[ChunkRecord]:
    """그래프에서 청크를 읽는다.

    `paper_ids`와 `expand_hops`를 함께 주면 지정한 논문에서 인용 관계를
    타고 이웃 논문까지 넓힌다. 멀티홉 질문을 만들려면 근거가 실제로
    연결된 논문들이 후보에 함께 있어야 하기 때문이다.
    """
    from linkpaper_eval.stores.neo4j_store import Neo4jStore

    settings = settings or StoreSettings.from_env()
    with Neo4jStore(settings.neo4j) as store:
        if paper_ids and expand_hops > 0:
            neighbors = store.related_papers(paper_ids, hops=expand_hops)
            paper_ids = list(dict.fromkeys([*paper_ids, *neighbors]))
        return list(store.iter_chunks(limit=limit, paper_ids=paper_ids))


def load_chunks(
    source: str,
    settings: StoreSettings | None = None,
    corpus: str | Path | None = None,
    limit: int | None = None,
    paper_ids: list[str] | None = None,
    expand_hops: int = 1,
) -> list[ChunkRecord]:
    """소스 이름으로 청크를 불러온다."""
    if source == "jsonl":
        if corpus is None:
            raise ValueError("source=jsonl 에는 --corpus 경로가 필요합니다.")
        chunks = from_jsonl(corpus, limit=limit)
        if paper_ids:
            allowed = set(paper_ids)
            chunks = [chunk for chunk in chunks if chunk.paper_id in allowed]
        return chunks
    if source == "qdrant":
        return from_qdrant(settings, limit=limit)
    if source == "neo4j":
        return from_neo4j(
            settings, limit=limit, paper_ids=paper_ids, expand_hops=expand_hops
        )
    raise ValueError(f"알 수 없는 소스: {source} (사용 가능: jsonl, neo4j, qdrant)")


def describe(chunks: list[ChunkRecord]) -> dict[str, Any]:
    papers = {chunk.paper_id for chunk in chunks}
    sections = {chunk.section for chunk in chunks if chunk.section}
    return {
        "chunk_count": len(chunks),
        "paper_count": len(papers),
        "section_count": len(sections),
        "avg_chars": (
            sum(len(chunk.text) for chunk in chunks) / len(chunks) if chunks else 0
        ),
    }

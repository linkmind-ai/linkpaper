"""벤치마크 코퍼스를 Qdrant와 Neo4j에 적재한다.

평가 대상이 DB에 붙어 있는 검색기이므로, 벤치마크 코퍼스도 같은 DB에
들어가야 비교가 성립한다. 적재는 멱등이다. 같은 코퍼스를 다시 넣으면
`chunk_id`가 같으므로 point와 노드가 덮어써질 뿐 중복되지 않는다.

주의: 이 명령은 데이터베이스에 쓴다. 서비스 DB와 평가 DB를 분리하고,
`QDRANT_COLLECTION`과 `NEO4J_DATABASE`를 평가용으로 지정한 뒤 실행한다.
Neo4j에 들어간 벤치마크 논문에는 `processingStatus = 'benchmark'`가 붙어서
나중에 `bench clean`으로 되돌릴 수 있다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from linkpaper_eval.benchmark.download import read_jsonl
from linkpaper_eval.stores.config import StoreSettings
from linkpaper_eval.stores.embedding import build_embedder
from linkpaper_eval.stores.records import ChunkRecord


class SeedReport(BaseModel):
    chunks: int = 0
    qdrant_points: int = 0
    neo4j_nodes: int = 0
    embedding: str = ""
    collection: str = ""
    notes: list[str] = []


def load_corpus(path: Path) -> list[ChunkRecord]:
    rows = read_jsonl(path)
    return [ChunkRecord.from_payload(row) for row in rows if row.get("text")]


def seed(
    corpus_path: Path,
    settings: StoreSettings | None = None,
    to_qdrant: bool = True,
    to_neo4j: bool = True,
    recreate: bool = False,
    batch_size: int = 128,
) -> SeedReport:
    settings = settings or StoreSettings.from_env()
    chunks = load_corpus(corpus_path)
    report = SeedReport(chunks=len(chunks), collection=settings.qdrant.collection)
    if not chunks:
        report.notes.append(f"코퍼스가 비어 있습니다: {corpus_path}")
        return report

    if to_qdrant:
        from linkpaper_eval.stores.qdrant_store import QdrantStore

        embedder = build_embedder(settings.embedding)
        report.embedding = embedder.signature()
        try:
            vectors = embedder.embed([chunk.text for chunk in chunks])
        finally:
            embedder.close()

        with QdrantStore(settings.qdrant) as store:
            store.ensure_collection(len(vectors[0]), recreate=recreate)
            report.qdrant_points = store.upsert_chunks(
                chunks, vectors, batch_size=batch_size
            )

    if to_neo4j:
        from linkpaper_eval.stores.neo4j_store import Neo4jStore

        with Neo4jStore(settings.neo4j) as store:
            store.ensure_schema()
            report.neo4j_nodes = store.upsert_chunks(chunks, batch_size=batch_size)

    return report

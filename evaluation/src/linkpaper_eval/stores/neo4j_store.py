"""Neo4j 그래프 저장소 어댑터.

라벨, 관계 타입, 속성 이름은 모두 `docs/data-architecture/neo4j-schema.md`를
따른다. 평가 하네스가 임의의 스키마를 새로 만들면 그래프 팀이 적재한
데이터와 어긋나므로, 여기서는 문서에 정의된 것만 사용한다.

읽기 경로(`iter_chunks`, `related_papers`, `graph_edges`)는 그래프 팀이
적재한 데이터를 그대로 평가하는 데 쓰고, 쓰기 경로(`upsert_chunks`)는
외부 벤치마크 코퍼스를 평가 전용 데이터베이스에 넣을 때만 쓴다.
운영 데이터베이스에 쓰기를 실행하지 않도록 CLI가 확인을 요구한다.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from linkpaper_eval.stores.config import Neo4jSettings
from linkpaper_eval.stores.records import ChunkRecord

_DRIVER_HINT = (
    "neo4j 드라이버가 없습니다. `pip install -e '.[stores]'` 로 설치하세요."
)

# 청크 노드를 ChunkRecord로 바꾸는 공통 projection.
_CHUNK_PROJECTION = """
    c.chunkId AS chunk_id,
    c.paperId AS paper_id,
    c.text AS text,
    c.section AS section,
    c.chunkIndex AS chunk_index
"""


class Neo4jStore:
    """Neo4j 연결 하나를 감싼다."""

    def __init__(self, settings: Neo4jSettings | None = None) -> None:
        self.settings = settings or Neo4jSettings()
        self._driver: Any | None = None

    @classmethod
    def from_env(cls, **overrides: Any) -> Neo4jStore:
        return cls(Neo4jSettings.from_env(**overrides))

    # ------------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------------

    @property
    def driver(self) -> Any:
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:  # pragma: no cover - 설치 여부에 따름
                raise RuntimeError(_DRIVER_HINT) from exc

            self._driver = GraphDatabase.driver(
                self.settings.uri,
                auth=(self.settings.username, self.settings.password),
                connection_timeout=self.settings.timeout_s,
            )
        return self._driver

    def ping(self) -> bool:
        """연결과 인증을 확인한다. 실패는 예외 대신 False로 돌려준다."""
        try:
            self.query("RETURN 1 AS ok")
        except Exception:  # noqa: BLE001 - doctor 명령이 원인을 따로 출력한다
            return False
        return True

    def query(
        self, cypher: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        with self.driver.session(database=self.settings.database) as session:
            result = session.run(cypher, parameters or {})
            return [record.data() for record in result]

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> Neo4jStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 읽기
    # ------------------------------------------------------------------

    def count_chunks(self) -> int:
        rows = self.query("MATCH (c:Chunk) RETURN count(c) AS total")
        return int(rows[0]["total"]) if rows else 0

    def iter_chunks(
        self,
        limit: int | None = None,
        paper_ids: Sequence[str] | None = None,
        batch_size: int = 500,
    ) -> Iterator[ChunkRecord]:
        """`:Chunk` 노드를 순서대로 읽는다.

        SKIP/LIMIT 페이지네이션은 정렬 기준이 안정적이어야 중복·누락이
        없다. `chunkId`가 전역 고유하므로 이것으로 정렬한다.
        """
        filter_clause = "WHERE c.paperId IN $paper_ids" if paper_ids else ""
        cypher = f"""
        MATCH (c:Chunk)
        {filter_clause}
        RETURN {_CHUNK_PROJECTION}
        ORDER BY c.chunkId
        SKIP $skip LIMIT $limit
        """

        fetched = 0
        skip = 0
        while True:
            page_size = batch_size
            if limit is not None:
                page_size = min(batch_size, limit - fetched)
                if page_size <= 0:
                    return

            rows = self.query(
                cypher,
                {
                    "paper_ids": list(paper_ids or []),
                    "skip": skip,
                    "limit": page_size,
                },
            )
            if not rows:
                return
            for row in rows:
                yield ChunkRecord.from_payload(row)
            fetched += len(rows)
            skip += len(rows)
            if len(rows) < page_size:
                return

    def fetch_chunks(self, chunk_ids: Sequence[str]) -> list[ChunkRecord]:
        if not chunk_ids:
            return []
        rows = self.query(
            f"""
            MATCH (c:Chunk)
            WHERE c.chunkId IN $chunk_ids
            RETURN {_CHUNK_PROJECTION}
            """,
            {"chunk_ids": list(chunk_ids)},
        )
        return [ChunkRecord.from_payload(row) for row in rows]

    def chunks_for_papers(
        self, paper_ids: Sequence[str], limit_per_paper: int = 20
    ) -> list[ChunkRecord]:
        """논문별로 앞쪽 청크를 가져온다. 그래프 확장 후보를 만들 때 쓴다."""
        if not paper_ids:
            return []
        rows = self.query(
            f"""
            MATCH (p:Paper)-[:HAS_CHUNK]->(c:Chunk)
            WHERE p.paperId IN $paper_ids
            WITH p, c ORDER BY c.chunkIndex
            WITH p, collect(c)[..$limit_per_paper] AS chunks
            UNWIND chunks AS c
            RETURN {_CHUNK_PROJECTION}
            """,
            {"paper_ids": list(paper_ids), "limit_per_paper": limit_per_paper},
        )
        return [ChunkRecord.from_payload(row) for row in rows]

    def related_papers(
        self, paper_ids: Sequence[str], hops: int = 1, limit: int = 25
    ) -> list[str]:
        """인용 관계로 연결된 논문 ID.

        방향을 구분하지 않는다. 선행 연구(`CITES` 나가는 방향)와 후속
        연구(`CITES` 들어오는 방향) 모두 LinkPaper의 탐색 대상이기
        때문이다.
        """
        if not paper_ids:
            return []
        depth = max(1, min(hops, 3))
        rows = self.query(
            f"""
            MATCH (p:Paper)-[:CITES*1..{depth}]-(related:Paper)
            WHERE p.paperId IN $paper_ids AND NOT related.paperId IN $paper_ids
            RETURN DISTINCT related.paperId AS paper_id
            LIMIT $limit
            """,
            {"paper_ids": list(paper_ids), "limit": limit},
        )
        return [row["paper_id"] for row in rows if row.get("paper_id")]

    def graph_edges(
        self, chunk_ids: Sequence[str], max_edges: int = 5000
    ) -> list[dict[str, Any]]:
        """청크 사이의 그래프 간선을 모은다.

        평가셋 생성기가 멀티홉 질문을 만들 때 "실제 그래프에서 연결된
        청크 쌍"을 골라야 한다. 임의의 두 청크를 묶으면 답이 없는 질문이
        나오므로, 근거가 되는 관계만 사용한다.

        - `next` : 같은 논문의 연속 청크
        - `same_paper` : 같은 논문의 다른 청크
        - `cites` : 인용 관계로 연결된 다른 논문의 청크
        - `shared_entity` : 같은 엔티티를 언급하는 다른 논문의 청크
        """
        if not chunk_ids:
            return []
        ids = list(chunk_ids)
        edges: list[dict[str, Any]] = []

        next_rows = self.query(
            """
            MATCH (a:Chunk)-[:NEXT_CHUNK]->(b:Chunk)
            WHERE a.chunkId IN $ids AND b.chunkId IN $ids
            RETURN a.chunkId AS source, b.chunkId AS target
            LIMIT $limit
            """,
            {"ids": ids, "limit": max_edges},
        )
        edges.extend({**row, "type": "next"} for row in next_rows)

        cites_rows = self.query(
            """
            MATCH (a:Chunk)<-[:HAS_CHUNK]-(p1:Paper)-[:CITES]->(p2:Paper)
                  -[:HAS_CHUNK]->(b:Chunk)
            WHERE a.chunkId IN $ids AND b.chunkId IN $ids
            RETURN a.chunkId AS source, b.chunkId AS target,
                   p1.paperId AS source_paper, p2.paperId AS target_paper
            LIMIT $limit
            """,
            {"ids": ids, "limit": max_edges},
        )
        edges.extend({**row, "type": "cites"} for row in cites_rows)

        entity_rows = self.query(
            """
            MATCH (a:Chunk)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(b:Chunk)
            WHERE a.chunkId IN $ids AND b.chunkId IN $ids
                  AND a.chunkId < b.chunkId AND a.paperId <> b.paperId
            RETURN a.chunkId AS source, b.chunkId AS target,
                   e.entityId AS entity_id
            LIMIT $limit
            """,
            {"ids": ids, "limit": max_edges},
        )
        edges.extend({**row, "type": "shared_entity"} for row in entity_rows)

        return edges

    # ------------------------------------------------------------------
    # 쓰기 (평가 전용 데이터베이스에만 사용한다)
    # ------------------------------------------------------------------

    def ensure_schema(self) -> None:
        """neo4j-schema.md 8장의 제약조건 중 평가에 필요한 것만 만든다."""
        statements = [
            "CREATE CONSTRAINT paper_id IF NOT EXISTS "
            "FOR (p:Paper) REQUIRE p.paperId IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS "
            "FOR (c:Chunk) REQUIRE c.chunkId IS UNIQUE",
            "CREATE INDEX chunk_paper IF NOT EXISTS "
            "FOR (c:Chunk) ON (c.paperId)",
        ]
        for statement in statements:
            self.query(statement)

    def upsert_chunks(
        self, chunks: Sequence[ChunkRecord], batch_size: int = 500
    ) -> int:
        """청크와 소속 논문을 upsert하고 `NEXT_CHUNK`를 잇는다."""
        rows = [
            {
                "chunk_id": chunk.chunk_id,
                "paper_id": chunk.paper_id,
                "text": chunk.text,
                "section": chunk.section,
                "chunk_index": chunk.chunk_index if chunk.chunk_index is not None else 0,
                "title": chunk.title,
            }
            for chunk in chunks
        ]
        written = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            self.query(
                """
                UNWIND $rows AS row
                MERGE (p:Paper {paperId: row.paper_id})
                  ON CREATE SET p.createdAt = datetime(),
                                p.processingStatus = 'benchmark'
                SET p.title = coalesce(row.title, p.title),
                    p.updatedAt = datetime()
                MERGE (c:Chunk {chunkId: row.chunk_id})
                SET c:GlobalChunk,
                    c.paperId = row.paper_id,
                    c.text = row.text,
                    c.section = row.section,
                    c.chunkIndex = row.chunk_index,
                    c.updatedAt = datetime()
                MERGE (p)-[:HAS_CHUNK]->(c)
                """,
                {"rows": batch},
            )
            written += len(batch)

        # 순서 관계는 논문 단위로 한 번에 잇는다. 청크가 배치에 나뉘어
        # 들어와도 마지막에 전체를 다시 잇기 때문에 누락되지 않는다.
        paper_ids = sorted({chunk.paper_id for chunk in chunks})
        self.query(
            """
            UNWIND $paper_ids AS pid
            MATCH (p:Paper {paperId: pid})-[:HAS_CHUNK]->(c:Chunk)
            WITH p, c ORDER BY c.chunkIndex
            WITH p, collect(c) AS ordered
            UNWIND range(0, size(ordered) - 2) AS i
            WITH ordered[i] AS a, ordered[i + 1] AS b
            MERGE (a)-[:NEXT_CHUNK]->(b)
            """,
            {"paper_ids": paper_ids},
        )
        return written

    def upsert_citations(self, pairs: Sequence[tuple[str, str]]) -> int:
        """`(citing, cited)` 논문 쌍으로 `CITES` 관계를 만든다."""
        rows = [{"source": source, "target": target} for source, target in pairs]
        if not rows:
            return 0
        self.query(
            """
            UNWIND $rows AS row
            MERGE (a:Paper {paperId: row.source})
            MERGE (b:Paper {paperId: row.target})
            MERGE (a)-[r:CITES]->(b)
            SET r.source = 'benchmark'
            """,
            {"rows": rows},
        )
        return len(rows)

    def delete_benchmark_data(self) -> int:
        """`processingStatus = 'benchmark'`인 논문과 청크를 지운다.

        벤치마크 적재를 되돌릴 때 쓴다. 서비스 데이터에는 이 값이 붙지
        않으므로 실수로 지워지지 않는다.
        """
        rows = self.query(
            """
            MATCH (p:Paper {processingStatus: 'benchmark'})
            OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c:Chunk)
            WITH collect(DISTINCT p) AS papers, collect(DISTINCT c) AS chunks
            WITH papers, chunks, size(papers) + size(chunks) AS removed
            FOREACH (n IN chunks | DETACH DELETE n)
            FOREACH (n IN papers | DETACH DELETE n)
            RETURN removed
            """
        )
        return int(rows[0]["removed"]) if rows else 0

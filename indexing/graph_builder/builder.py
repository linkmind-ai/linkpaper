"""Neo4j 구조 그래프 builder.

MVP에서는 Paper·Author·Chunk 구조와 CITES를 만든다. Entity와 의미 Triple
추출은 별도의 extractor가 확정된 뒤 이 builder 앞 단계에 연결한다.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Self

from data_pipeline.models import ProcessedPaper
from indexing_common import BuilderSettings, IndexingContractError, canonicalize_paper

logger = logging.getLogger(__name__)

_DRIVER_HINT = "neo4j 드라이버가 없습니다. indexing 의존성을 설치하세요."

SCHEMA_STATEMENTS = (
    (
        "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS "
        "FOR (p:Paper) REQUIRE p.paperId IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT author_id_unique IF NOT EXISTS "
        "FOR (a:Author) REQUIRE a.authorId IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS "
        "FOR (c:Chunk) REQUIRE c.chunkId IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS "
        "FOR (e:Entity) REQUIRE e.entityId IS UNIQUE"
    ),
    "CREATE RANGE INDEX paper_arxiv_id IF NOT EXISTS FOR (p:Paper) ON (p.arxivId)",
    "CREATE RANGE INDEX chunk_paper_id IF NOT EXISTS FOR (c:Chunk) ON (c.paperId)",
    (
        "CREATE RANGE INDEX author_normalized_name IF NOT EXISTS "
        "FOR (a:Author) ON (a.normalizedName)"
    ),
    (
        "CREATE RANGE INDEX entity_normalized_name IF NOT EXISTS "
        "FOR (e:Entity) ON (e.normalizedName)"
    ),
)

_UPSERT_PAPER = """
MERGE (p:Paper {paperId: $paper.paperId})
ON CREATE SET p.createdAt = datetime()
SET p.arxivId = $paper.arxivId,
    p.title = $paper.title,
    p.abstract = $paper.abstract,
    p.publishedAt = CASE
        WHEN $paper.publishedAt IS NULL THEN NULL ELSE date($paper.publishedAt)
    END,
    p.sourceVersion = $paper.sourceVersion,
    p.sourceUrl = $paper.sourceUrl,
    p.pdfUrl = $paper.pdfUrl,
    p.processingStatus = 'completed',
    p.contentHash = $paper.contentHash,
    p.schemaVersion = $paper.schemaVersion,
    p.updatedAt = datetime()
"""

_SET_GLOBAL_PAPER = "MATCH (p:Paper {paperId: $paperId}) SET p:GlobalPaper"

_DELETE_STALE_CHUNKS = """
MATCH (p:Paper {paperId: $paperId})-[:HAS_CHUNK]->(old:Chunk)
WHERE NOT old.chunkId IN $chunkIds
DETACH DELETE old
"""

_UPSERT_CHUNKS = """
MATCH (p:Paper {paperId: $paperId})
UNWIND $chunks AS chunk
MERGE (c:Chunk {chunkId: chunk.chunkId})
ON CREATE SET c.createdAt = datetime()
SET c.paperId = $paperId,
    c.chunkIndex = chunk.chunkIndex,
    c.text = chunk.text,
    c.section = chunk.section,
    c.charCount = chunk.charCount,
    c.contentHash = chunk.contentHash,
    c.updatedAt = datetime()
MERGE (p)-[:HAS_CHUNK]->(c)
"""

_SET_GLOBAL_CHUNKS = """
UNWIND $chunkIds AS chunkId
MATCH (c:Chunk {chunkId: chunkId})
SET c:GlobalChunk
"""

_REPLACE_NEXT_CHUNKS = """
MATCH (p:Paper {paperId: $paperId})-[:HAS_CHUNK]->(c:Chunk)
OPTIONAL MATCH (c)-[old:NEXT_CHUNK]->(:Chunk)
DELETE old
WITH DISTINCT p
UNWIND $pairs AS pair
MATCH (p)-[:HAS_CHUNK]->(left:Chunk {chunkId: pair.left})
MATCH (p)-[:HAS_CHUNK]->(right:Chunk {chunkId: pair.right})
MERGE (left)-[:NEXT_CHUNK]->(right)
"""

_REPLACE_AUTHORS = """
MATCH (p:Paper {paperId: $paperId})
OPTIONAL MATCH (p)-[old:AUTHORED_BY]->(:Author)
DELETE old
WITH DISTINCT p
UNWIND $authors AS author
MERGE (a:Author {authorId: author.authorId})
ON CREATE SET a.createdAt = datetime()
SET a.name = author.name,
    a.normalizedName = author.normalizedName,
    a.updatedAt = datetime()
MERGE (p)-[r:AUTHORED_BY]->(a)
SET r.authorOrder = author.authorOrder,
    r.source = 'huggingface'
"""

_REPLACE_CITATIONS = """
MATCH (p:Paper {paperId: $paperId})
OPTIONAL MATCH (p)-[old:CITES]->(:Paper)
DELETE old
WITH DISTINCT p
UNWIND $references AS reference
MERGE (cited:Paper {paperId: reference.paperId})
ON CREATE SET cited.arxivId = reference.arxivId,
              cited.title = reference.title,
              cited.processingStatus = 'reference_only',
              cited.schemaVersion = $schemaVersion,
              cited.createdAt = datetime(),
              cited.updatedAt = datetime()
MERGE (p)-[:CITES]->(cited)
"""


@dataclass(frozen=True)
class GraphBuildResult:
    paper_id: str
    chunks: int
    authors: int
    citations: int


def _consume(result: Any) -> None:
    """드라이버가 쿼리를 서버에 끝까지 전달하도록 결과를 소비한다."""
    if hasattr(result, "consume"):
        result.consume()


def _normalize_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _author_rows(paper_id: str, names: list[str]) -> list[dict[str, Any]]:
    authors: list[dict[str, Any]] = []
    for order, name in enumerate(names):
        normalized_name = _normalize_name(name)
        # 이름만으로 동명이인을 병합하지 않도록 논문·순서를 provisional ID에 넣는다.
        digest = hashlib.sha256(
            f"{paper_id}|{order}|{normalized_name}".encode()
        ).hexdigest()[:20]
        authors.append(
            {
                "authorId": f"author:provisional:{digest}",
                "name": name.strip(),
                "normalizedName": normalized_name,
                "authorOrder": order,
            }
        )
    return authors


def prepare_graph_payload(
    source: ProcessedPaper, schema_version: str
) -> dict[str, Any]:
    """Pydantic 입력을 Cypher 파라미터로 변환하고 필수 계약을 검증한다."""
    paper = canonicalize_paper(source)
    metadata = paper.metadata
    if not metadata.title or not metadata.source_version or not metadata.content_hash:
        raise IndexingContractError(
            f"{metadata.paper_id}: title/source_version/content_hash가 필요합니다"
        )
    if not paper.chunks:
        raise IndexingContractError(
            f"{metadata.paper_id}: completed 논문에는 청크가 필요합니다"
        )

    chunks = [
        {
            "chunkId": chunk.chunk_id,
            "chunkIndex": chunk.chunk_index,
            "text": chunk.text,
            "section": chunk.section or None,
            "charCount": chunk.char_count,
            "contentHash": chunk.content_hash,
        }
        for chunk in sorted(paper.chunks, key=lambda item: item.chunk_index)
    ]
    chunk_ids = [chunk["chunkId"] for chunk in chunks]
    pairs = [{"left": left, "right": right} for left, right in pairwise(chunk_ids)]
    references = [
        {
            "paperId": reference,
            "arxivId": reference.removeprefix("arxiv:")
            if reference.startswith("arxiv:")
            else None,
            "title": reference.removeprefix("arxiv:")
            .removeprefix("hf:")
            .removeprefix("ref:"),
        }
        for reference in metadata.references
        if reference != metadata.paper_id
    ]
    return {
        "paper": {
            "paperId": metadata.paper_id,
            "arxivId": metadata.arxiv_id,
            "title": metadata.title,
            "abstract": metadata.abstract or None,
            "publishedAt": metadata.published_at.date().isoformat()
            if metadata.published_at
            else None,
            "sourceVersion": metadata.source_version,
            "sourceUrl": metadata.source_url or None,
            "pdfUrl": metadata.pdf_url,
            "contentHash": metadata.content_hash,
            "schemaVersion": schema_version,
        },
        "authors": _author_rows(metadata.paper_id, metadata.authors),
        "chunks": chunks,
        "chunkIds": chunk_ids,
        "pairs": pairs,
        "references": references,
    }


class Neo4jGraphBuilder:
    """논문 단위 Neo4j 트랜잭션을 제공한다."""

    def __init__(
        self,
        settings: BuilderSettings | None = None,
        driver: Any | None = None,
    ) -> None:
        self.settings = settings or BuilderSettings()
        self._driver = driver

    @property
    def driver(self) -> Any:
        if self._driver is None:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:  # pragma: no cover - 설치 환경에 따름
                raise RuntimeError(_DRIVER_HINT) from exc
            self._driver = GraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_username, self.settings.neo4j_password),
            )
        return self._driver

    def ensure_schema(self) -> None:
        """제약조건과 조회 인덱스를 멱등하게 초기화한다."""
        with self.driver.session(database=self.settings.neo4j_database) as session:
            for statement in SCHEMA_STATEMENTS:
                _consume(session.run(statement))

    def upsert(
        self, source: ProcessedPaper, *, in_global_corpus: bool = False
    ) -> GraphBuildResult:
        payload = prepare_graph_payload(source, self.settings.schema_version)
        with self.driver.session(database=self.settings.neo4j_database) as session:
            # 논문 한 편의 구조 그래프를 한 트랜잭션으로 묶어 부분 그래프를 막는다.
            session.execute_write(self._write_paper, payload, in_global_corpus)

        result = GraphBuildResult(
            paper_id=payload["paper"]["paperId"],
            chunks=len(payload["chunks"]),
            authors=len(payload["authors"]),
            citations=len(payload["references"]),
        )
        logger.info("Neo4j 적재 완료 %s", result)
        return result

    def upsert_many(
        self, papers: list[ProcessedPaper], *, in_global_corpus: bool = False
    ) -> list[GraphBuildResult]:
        return [
            self.upsert(paper, in_global_corpus=in_global_corpus) for paper in papers
        ]

    @staticmethod
    def _write_paper(tx: Any, payload: dict[str, Any], is_global: bool) -> None:
        paper_id = payload["paper"]["paperId"]
        _consume(tx.run(_UPSERT_PAPER, paper=payload["paper"]))
        if is_global:
            _consume(tx.run(_SET_GLOBAL_PAPER, paperId=paper_id))

        # 새 ID 목록에 없는 과거 청크를 먼저 제거해 재청킹 뒤 orphan을 남기지 않는다.
        _consume(
            tx.run(
                _DELETE_STALE_CHUNKS,
                paperId=paper_id,
                chunkIds=payload["chunkIds"],
            )
        )
        _consume(
            tx.run(
                _UPSERT_CHUNKS,
                paperId=paper_id,
                chunks=payload["chunks"],
            )
        )
        if is_global:
            _consume(tx.run(_SET_GLOBAL_CHUNKS, chunkIds=payload["chunkIds"]))

        _consume(
            tx.run(
                _REPLACE_NEXT_CHUNKS,
                paperId=paper_id,
                pairs=payload["pairs"],
            )
        )
        _consume(
            tx.run(
                _REPLACE_AUTHORS,
                paperId=paper_id,
                authors=payload["authors"],
            )
        )
        # 현재 JSON은 ID 목록만 제공하므로 MVP CITES에는 근거 속성을 넣지 않는다.
        _consume(
            tx.run(
                _REPLACE_CITATIONS,
                paperId=paper_id,
                references=payload["references"],
                schemaVersion=payload["paper"]["schemaVersion"],
            )
        )

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

"""완성된 Neo4j 그래프를 읽는 온라인 전용 서비스."""

from __future__ import annotations

from typing import Any

from linkpaper.core.config import Settings, get_settings
from linkpaper.core.exceptions import StoreSchemaMismatchError
from linkpaper.modules.knowledge_graph.models import (
    AuthorNode,
    ChunkNode,
    CitationEdge,
    GraphExpansion,
    KnowledgeGraph,
    PaperNode,
)

_PAPER_EXISTS = """
MATCH (p:Paper {paperId: $paper_id})
WHERE NOT $global_only OR p:GlobalPaper
RETURN count(p) > 0 AS exists
"""

_PAPER_GRAPH = """
MATCH (p:Paper {paperId: $paper_id})
WHERE NOT $global_only OR p:GlobalPaper
OPTIONAL MATCH (p)-[authored:AUTHORED_BY]->(a:Author)
WITH p, collect(a {
    author_id: a.authorId,
    name: a.name,
    normalized_name: a.normalizedName,
    author_order: authored.authorOrder
}) AS authors
OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c:Chunk)
WITH p, authors, collect(c {
    chunk_id: c.chunkId,
    paper_id: c.paperId,
    chunk_index: c.chunkIndex,
    text: c.text,
    section: c.section,
    char_count: c.charCount,
    content_hash: c.contentHash,
    in_global_corpus: c:GlobalChunk
}) AS chunks
OPTIONAL MATCH (p)-[cites:CITES]->(cited:Paper)
RETURN p {
    paper_id: p.paperId,
    arxiv_id: p.arxivId,
    title: p.title,
    abstract: p.abstract,
    published_at: toString(p.publishedAt),
    source_version: p.sourceVersion,
    source_url: p.sourceUrl,
    pdf_url: p.pdfUrl,
    processing_status: p.processingStatus,
    content_hash: p.contentHash,
    schema_version: p.schemaVersion,
    in_global_corpus: p:GlobalPaper
} AS paper,
authors,
chunks,
collect(cited {
    source_paper_id: p.paperId,
    target_paper_id: cited.paperId
}) AS citations
"""

_EXPAND_CITATIONS = """
UNWIND $chunk_ids AS requested_chunk_id
MATCH (chunk:Chunk {chunkId: requested_chunk_id})<-[:HAS_CHUNK]-(source:Paper)
MATCH (source)-[relation:CITES]-(related:Paper)
WHERE NOT $global_only OR related:GlobalPaper
RETURN DISTINCT
    chunk.chunkId AS source_chunk_id,
    source.paperId AS source_paper_id,
    type(relation) AS relationship_type,
    related {
        paper_id: related.paperId,
        arxiv_id: related.arxivId,
        title: related.title,
        abstract: related.abstract,
        published_at: toString(related.publishedAt),
        source_version: related.sourceVersion,
        source_url: related.sourceUrl,
        pdf_url: related.pdfUrl,
        processing_status: related.processingStatus,
        content_hash: related.contentHash,
        schema_version: related.schemaVersion,
        in_global_corpus: related:GlobalPaper
    } AS related_paper
LIMIT $limit
"""


class KnowledgeGraphService:
    """Paper·Chunk·Author·CITES 구조를 조회하며 write API는 노출하지 않는다."""

    def __init__(
        self,
        settings: Settings | None = None,
        driver: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._driver = driver

    @property
    def driver(self) -> Any:
        if self._driver is None:
            from neo4j import AsyncGraphDatabase

            self._driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(
                    self.settings.neo4j_username,
                    self.settings.neo4j_password,
                ),
            )
        return self._driver

    async def verify_connection(self) -> None:
        await self.driver.verify_connectivity()

    async def has_paper(self, paper_id: str, *, global_only: bool = False) -> bool:
        async with self.driver.session(
            database=self.settings.neo4j_database
        ) as session:
            result = await session.run(
                _PAPER_EXISTS,
                paper_id=paper_id,
                global_only=global_only,
            )
            record = await result.single()
        return bool(record and record["exists"])

    async def get_paper_graph(
        self,
        paper_id: str,
        *,
        global_only: bool = False,
    ) -> KnowledgeGraph | None:
        async with self.driver.session(
            database=self.settings.neo4j_database
        ) as session:
            result = await session.run(
                _PAPER_GRAPH,
                paper_id=paper_id,
                global_only=global_only,
            )
            record = await result.single()
        if record is None:
            return None

        data = record.data() if hasattr(record, "data") else dict(record)
        paper = self._paper_node(data["paper"])
        authors = [AuthorNode.model_validate(item) for item in data["authors"]]
        chunks = [ChunkNode.model_validate(item) for item in data["chunks"]]
        citations = [CitationEdge.model_validate(item) for item in data["citations"]]
        return KnowledgeGraph(
            paper=paper,
            authors=sorted(authors, key=lambda item: item.author_order),
            chunks=sorted(chunks, key=lambda item: item.chunk_index),
            citations=citations,
        )

    async def expand_citations(
        self,
        chunk_ids: list[str],
        *,
        global_only: bool = False,
        limit: int = 50,
    ) -> list[GraphExpansion]:
        if not chunk_ids:
            return []
        if not 1 <= limit <= 500:
            raise ValueError("limit은 1 이상 500 이하여야 합니다")

        # Qdrant 결과의 공통 join key인 chunk_id를 그래프 탐색 시작점으로 사용한다.
        async with self.driver.session(
            database=self.settings.neo4j_database
        ) as session:
            result = await session.run(
                _EXPAND_CITATIONS,
                chunk_ids=list(dict.fromkeys(chunk_ids)),
                global_only=global_only,
                limit=limit,
            )
            records = [record async for record in result]

        expansions: list[GraphExpansion] = []
        for record in records:
            data = record.data() if hasattr(record, "data") else dict(record)
            expansions.append(
                GraphExpansion(
                    source_chunk_id=data["source_chunk_id"],
                    source_paper_id=data["source_paper_id"],
                    relationship_type=data["relationship_type"],
                    related_paper=self._paper_node(data["related_paper"]),
                )
            )
        return expansions

    def _paper_node(self, value: dict[str, Any]) -> PaperNode:
        paper = PaperNode.model_validate(value)
        expected_version = self.settings.linkpaper_schema_version
        # reference_only stub도 생성 시 현재 schemaVersion을 가져야 한다.
        if paper.schema_version != expected_version:
            raise StoreSchemaMismatchError(
                "Neo4j 스키마 버전 불일치: "
                f"paper={paper.schema_version}, expected={expected_version}"
            )
        return paper

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

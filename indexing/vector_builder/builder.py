"""Qdrant 청크 벡터 builder."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Self

from data_pipeline.models import ProcessedPaper
from indexing_common import BuilderSettings, IndexingContractError, canonicalize_paper
from vector_builder.embedding import Embedder, build_embedder

logger = logging.getLogger(__name__)

_CLIENT_HINT = "qdrant-client가 없습니다. indexing 의존성을 설치하세요."


@dataclass(frozen=True)
class PreparedVectorPoint:
    point_id: str
    chunk_id: str
    text: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorBuildResult:
    paper_id: str
    points: int
    skipped_reference_chunks: int


def point_id_for(chunk_id: str) -> str:
    """Chunk ID로부터 재실행해도 바뀌지 않는 Qdrant UUID를 만든다."""
    # 문서 계약의 namespace와 prefix를 그대로 사용해야 기존 point를 덮어쓴다.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"linkpaper:chunk:{chunk_id}"))


def prepare_vector_points(
    source: ProcessedPaper,
    *,
    in_global_corpus: bool,
    include_reference_chunks: bool,
    embedder: Embedder,
    embedding_version: str,
) -> tuple[str, list[PreparedVectorPoint], int]:
    """정규화 입력을 임베딩 전 Qdrant point 계약으로 변환한다."""
    paper = canonicalize_paper(source)
    metadata = paper.metadata
    if not metadata.title or not metadata.source_version or not metadata.content_hash:
        raise IndexingContractError(
            f"{metadata.paper_id}: title/source_version/content_hash가 필요합니다"
        )

    points: list[PreparedVectorPoint] = []
    skipped = 0
    for chunk in sorted(paper.chunks, key=lambda item: item.chunk_index):
        if chunk.is_references and not include_reference_chunks:
            skipped += 1
            continue
        payload = {
            "chunk_id": chunk.chunk_id,
            "paper_id": metadata.paper_id,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "section": chunk.section or None,
            "char_count": chunk.char_count,
            "content_hash": chunk.content_hash,
            "title": metadata.title,
            "published_at": metadata.published_at.isoformat()
            if metadata.published_at
            else None,
            "source_version": metadata.source_version,
            "in_global_corpus": in_global_corpus,
            "embedding_provider": embedder.provider,
            "embedding_model": embedder.model,
            "embedding_dimension": embedder.dimensions,
            "embedding_version": embedding_version,
        }
        points.append(
            PreparedVectorPoint(
                point_id=point_id_for(chunk.chunk_id),
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                payload=payload,
            )
        )
    return metadata.paper_id, points, skipped


class QdrantVectorBuilder:
    """청크 임베딩과 Qdrant 동기화를 논문 단위로 수행한다."""

    def __init__(
        self,
        settings: BuilderSettings | None = None,
        client: Any | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings or BuilderSettings()
        self._client = client
        self._embedder = embedder
        self._collection_ready = False

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:  # pragma: no cover - 설치 환경에 따름
                raise RuntimeError(_CLIENT_HINT) from exc
            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key,
                timeout=30,
            )
        return self._client

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = build_embedder(self.settings)
        return self._embedder

    def ensure_collection(self) -> None:
        """컬렉션을 만들거나 기존 벡터 차원이 설정과 같은지 검증한다."""
        from qdrant_client import models

        if self._collection_ready:
            return
        name = self.settings.qdrant_collection
        if self.client.collection_exists(name):
            info = self.client.get_collection(name)
            vector_config = info.config.params.vectors
            if isinstance(vector_config, dict):
                raise IndexingContractError("named vector 컬렉션은 지원하지 않습니다")
            if int(vector_config.size) != self.embedder.dimensions:
                raise IndexingContractError(
                    f"Qdrant 차원 불일치: collection={vector_config.size}, "
                    f"embedder={self.embedder.dimensions}"
                )
            distance = str(vector_config.distance).casefold().split(".")[-1]
            if distance != "cosine":
                raise IndexingContractError(
                    f"Qdrant 거리 함수 불일치: collection={vector_config.distance}, "
                    "expected=Cosine"
                )
            self._collection_ready = True
            return

        self.client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=self.embedder.dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        # 온라인 검색에서 사용하는 필터만 payload index로 만든다.
        for field_name, schema in (
            ("chunk_id", models.PayloadSchemaType.KEYWORD),
            ("paper_id", models.PayloadSchemaType.KEYWORD),
            ("in_global_corpus", models.PayloadSchemaType.BOOL),
        ):
            self.client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=schema,
                wait=True,
            )
        self._collection_ready = True

    def upsert(
        self, source: ProcessedPaper, *, in_global_corpus: bool = False
    ) -> VectorBuildResult:
        paper_id, points, skipped = prepare_vector_points(
            source,
            in_global_corpus=in_global_corpus,
            include_reference_chunks=self.settings.include_reference_chunks,
            embedder=self.embedder,
            embedding_version=self.settings.embedding_version,
        )
        # 컬렉션 계약을 먼저 검사해 차원 불일치 상태에서 API 임베딩 비용을 쓰지 않는다.
        self.ensure_collection()
        if not in_global_corpus and self._is_existing_global(paper_id):
            # base로 편입된 논문을 paper/daily 재처리가 글로벌 범위에서 내리지 않는다.
            for point in points:
                point.payload["in_global_corpus"] = True
        vectors = self.embedder.embed([point.text for point in points])
        self._validate_vectors(points, vectors)
        self._upsert_batches(points, vectors)
        # 새 point가 안전하게 올라간 뒤 과거 청킹 결과만 제거한다.
        self._delete_stale_points(paper_id, [point.point_id for point in points])

        result = VectorBuildResult(
            paper_id=paper_id,
            points=len(points),
            skipped_reference_chunks=skipped,
        )
        logger.info("Qdrant 적재 완료 %s", result)
        return result

    def upsert_many(
        self, papers: list[ProcessedPaper], *, in_global_corpus: bool = False
    ) -> list[VectorBuildResult]:
        return [
            self.upsert(paper, in_global_corpus=in_global_corpus) for paper in papers
        ]

    def _validate_vectors(
        self,
        points: list[PreparedVectorPoint],
        vectors: list[list[float]],
    ) -> None:
        if len(points) != len(vectors):
            raise IndexingContractError(
                f"청크 {len(points)}개와 벡터 {len(vectors)}개의 수가 다릅니다"
            )
        if any(len(vector) != self.embedder.dimensions for vector in vectors):
            raise IndexingContractError(
                f"임베딩 벡터 차원은 {self.embedder.dimensions}이어야 합니다"
            )

    def _upsert_batches(
        self,
        points: list[PreparedVectorPoint],
        vectors: list[list[float]],
    ) -> None:
        from qdrant_client import models

        size = self.settings.qdrant_batch_size
        for start in range(0, len(points), size):
            point_batch = points[start : start + size]
            vector_batch = vectors[start : start + size]
            structs = [
                models.PointStruct(
                    id=point.point_id,
                    vector=vector,
                    payload=point.payload,
                )
                for point, vector in zip(point_batch, vector_batch)
            ]
            self.client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=structs,
                wait=True,
            )

    def _delete_stale_points(self, paper_id: str, current_ids: list[str]) -> None:
        from qdrant_client import models

        conditions: dict[str, Any] = {
            "must": [
                models.FieldCondition(
                    key="paper_id", match=models.MatchValue(value=paper_id)
                )
            ]
        }
        if current_ids:
            # 현재 point ID를 제외한 같은 논문의 과거 point만 삭제한다.
            conditions["must_not"] = [models.HasIdCondition(has_id=current_ids)]
        self.client.delete(
            collection_name=self.settings.qdrant_collection,
            points_selector=models.FilterSelector(filter=models.Filter(**conditions)),
            wait=True,
        )

    def _is_existing_global(self, paper_id: str) -> bool:
        from qdrant_client import models

        records, _ = self.client.scroll(
            collection_name=self.settings.qdrant_collection,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="paper_id", match=models.MatchValue(value=paper_id)
                    )
                ]
            ),
            limit=1,
            with_payload=["in_global_corpus"],
            with_vectors=False,
        )
        return bool(
            records
            and records[0].payload
            and records[0].payload.get("in_global_corpus")
        )

    def close(self) -> None:
        if self._embedder is not None:
            self._embedder.close()
            self._embedder = None
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close:
                close()
            self._client = None
        self._collection_ready = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

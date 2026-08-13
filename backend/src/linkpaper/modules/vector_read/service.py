"""완성된 Qdrant 인덱스를 읽는 온라인 전용 서비스."""

from __future__ import annotations

from typing import Any

from linkpaper.core.config import Settings, get_settings
from linkpaper.core.exceptions import StoreSchemaMismatchError
from linkpaper.modules.vector_read.models import (
    VectorChunkPayload,
    VectorSearchHit,
    VectorSearchRequest,
    VectorSearchScope,
)


class VectorReadService:
    """Qdrant payload 필터 검색을 제공하며 write API는 노출하지 않는다."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key or None,
                timeout=30,
            )
        return self._client

    async def verify_schema(self) -> None:
        """서비스 시작 또는 운영 점검에서 컬렉션 벡터 계약을 확인한다."""
        info = await self.client.get_collection(self.settings.qdrant_collection)
        vector_config = info.config.params.vectors
        if isinstance(vector_config, dict):
            raise StoreSchemaMismatchError("named vector 컬렉션은 지원하지 않습니다")

        actual_dimension = int(vector_config.size)
        expected_dimension = self.settings.linkpaper_embedding_dimensions
        if actual_dimension != expected_dimension:
            raise StoreSchemaMismatchError(
                "Qdrant 벡터 차원 불일치: "
                f"collection={actual_dimension}, expected={expected_dimension}"
            )

        distance = str(vector_config.distance).casefold().split(".")[-1]
        if distance != "cosine":
            raise StoreSchemaMismatchError(
                f"Qdrant 거리 함수 불일치: collection={vector_config.distance}, "
                "expected=Cosine"
            )

    async def has_paper(self, paper_id: str) -> bool:
        """논문에 속한 벡터 point가 하나라도 있는지 확인한다."""
        records, _ = await self.client.scroll(
            collection_name=self.settings.qdrant_collection,
            scroll_filter={
                "must": [
                    {"key": "paper_id", "match": {"value": paper_id}},
                ]
            },
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return bool(records)

    async def search(self, request: VectorSearchRequest) -> list[VectorSearchHit]:
        expected_dimension = self.settings.linkpaper_embedding_dimensions
        if len(request.query_vector) != expected_dimension:
            raise StoreSchemaMismatchError(
                "질의 벡터 차원 불일치: "
                f"query={len(request.query_vector)}, expected={expected_dimension}"
            )

        # 적재 규칙과 동일한 payload key로 선택 논문 또는 글로벌 범위를 제한한다.
        if request.scope is VectorSearchScope.SELECTED_PAPER:
            must = [
                {"key": "paper_id", "match": {"value": request.paper_id}},
            ]
        else:
            must = [
                {"key": "in_global_corpus", "match": {"value": True}},
            ]

        response = await self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=request.query_vector,
            query_filter={"must": must},
            limit=request.limit,
            score_threshold=request.score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        points = response.points if hasattr(response, "points") else response
        return [self._to_search_hit(point) for point in points]

    def _to_search_hit(self, point: Any) -> VectorSearchHit:
        payload = VectorChunkPayload.model_validate(point.payload or {})
        expected_signature = (
            self.settings.linkpaper_embedding_provider,
            self.settings.linkpaper_embedding_model,
            self.settings.linkpaper_embedding_dimensions,
            self.settings.linkpaper_embedding_version,
        )
        actual_signature = (
            payload.embedding_provider,
            payload.embedding_model,
            payload.embedding_dimension,
            payload.embedding_version,
        )
        # 한 컬렉션 안에 다른 임베딩 버전의 point가 섞이는 사고를 즉시 드러낸다.
        if actual_signature != expected_signature:
            raise StoreSchemaMismatchError(
                "Qdrant 임베딩 서명 불일치: "
                f"point={actual_signature}, expected={expected_signature}"
            )
        return VectorSearchHit(
            point_id=str(point.id),
            score=float(point.score),
            payload=payload,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

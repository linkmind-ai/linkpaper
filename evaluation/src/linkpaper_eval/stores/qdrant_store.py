"""Qdrant 벡터 저장소 어댑터.

컬렉션 하나가 청크 벡터 인덱스 하나에 대응한다. payload에는 평가에
필요한 최소 필드(`chunk_id`, `paper_id`, `text`, `section`)만 둔다.
`chunk_id`가 payload에 없으면 검색 결과를 정답과 대조할 수 없으므로,
적재 시 반드시 채운다.

Qdrant의 point ID는 부호 없는 정수 또는 UUID만 허용한다. `chunk_id`는
문자열이라 그대로 쓸 수 없으므로 UUIDv5로 결정적으로 변환한다. 같은
청크를 다시 넣으면 같은 point를 덮어쓰므로 중복이 생기지 않는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from typing import Any

from linkpaper_eval.stores.config import QdrantSettings
from linkpaper_eval.stores.records import ChunkRecord, SearchHit

_CLIENT_HINT = (
    "qdrant-client가 없습니다. `pip install -e '.[stores]'` 로 설치하세요."
)

# chunk_id → point UUID 변환용 고정 네임스페이스.
_NAMESPACE = uuid.UUID("6f6e2f2d-6c69-6e6b-7061-706572000001")


def point_id_for(chunk_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


class QdrantStore:
    """Qdrant 컬렉션 하나를 감싼다."""

    def __init__(self, settings: QdrantSettings | None = None) -> None:
        self.settings = settings or QdrantSettings()
        self._client: Any | None = None

    @classmethod
    def from_env(cls, **overrides: Any) -> QdrantStore:
        return cls(QdrantSettings.from_env(**overrides))

    # ------------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:  # pragma: no cover - 설치 여부에 따름
                raise RuntimeError(_CLIENT_HINT) from exc

            # `:memory:`와 로컬 경로는 서버 없이 도는 임베디드 모드다.
            # Docker 없이 벡터 경로 전체를 실행해 볼 수 있어서, 테스트와
            # 소규모 실험에 쓴다. 서버 모드와 API가 같으므로 어댑터 코드는
            # 갈라지지 않는다.
            if self.settings.url == ":memory:":
                self._client = QdrantClient(location=":memory:")
            elif self.settings.url.startswith("file://"):
                self._client = QdrantClient(path=self.settings.url[len("file://") :])
            else:
                self._client = QdrantClient(
                    url=self.settings.url,
                    api_key=self.settings.api_key,
                    timeout=int(self.settings.timeout_s),
                    prefer_grpc=self.settings.prefer_grpc,
                )
        return self._client

    def ping(self) -> bool:
        try:
            self.client.get_collections()
        except Exception:  # noqa: BLE001 - doctor 명령이 원인을 따로 출력한다
            return False
        return True

    def collection_exists(self) -> bool:
        try:
            return bool(self.client.collection_exists(self.settings.collection))
        except AttributeError:  # pragma: no cover - 구버전 클라이언트
            names = {c.name for c in self.client.get_collections().collections}
            return self.settings.collection in names

    def count(self) -> int:
        if not self.collection_exists():
            return 0
        return int(self.client.count(self.settings.collection, exact=True).count)

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001 - 이미 닫혔거나 지원하지 않는 경우
                pass
            self._client = None

    def __enter__(self) -> QdrantStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # 적재
    # ------------------------------------------------------------------

    def ensure_collection(self, vector_size: int, recreate: bool = False) -> None:
        """컬렉션을 만든다. 이미 있으면 그대로 둔다.

        차원이 다른 컬렉션에 벡터를 넣으면 Qdrant가 거부한다. 임베딩
        모델을 바꿨다면 `recreate=True`로 다시 만들어야 한다.
        """
        from qdrant_client import models

        if recreate and self.collection_exists():
            self.client.delete_collection(self.settings.collection)

        if self.collection_exists():
            return

        vectors_config: Any = models.VectorParams(
            size=vector_size, distance=models.Distance.COSINE
        )
        if self.settings.vector_name:
            vectors_config = {self.settings.vector_name: vectors_config}

        self.client.create_collection(
            collection_name=self.settings.collection,
            vectors_config=vectors_config,
        )
        # paper_id 필터가 자주 쓰이므로 payload 인덱스를 만들어 둔다.
        # 임베디드 모드에는 인덱스 개념이 없어서 경고만 내므로 건너뛴다.
        # 필터 자체는 인덱스 없이도 동작한다.
        if self.settings.url == ":memory:" or self.settings.url.startswith("file://"):
            return
        self.client.create_payload_index(
            collection_name=self.settings.collection,
            field_name="paper_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

    def upsert_chunks(
        self,
        chunks: Sequence[ChunkRecord],
        vectors: Sequence[Sequence[float]],
        batch_size: int = 128,
    ) -> int:
        from qdrant_client import models

        if len(chunks) != len(vectors):
            raise ValueError(
                f"청크 {len(chunks)}개와 벡터 {len(vectors)}개의 수가 다릅니다."
            )

        written = 0
        for start in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start : start + batch_size]
            batch_vectors = vectors[start : start + batch_size]
            points = [
                models.PointStruct(
                    id=point_id_for(chunk.chunk_id),
                    vector=(
                        {self.settings.vector_name: list(vector)}
                        if self.settings.vector_name
                        else list(vector)
                    ),
                    payload=chunk.to_payload(),
                )
                for chunk, vector in zip(batch_chunks, batch_vectors)
            ]
            self.client.upsert(
                collection_name=self.settings.collection, points=points, wait=True
            )
            written += len(points)
        return written

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------

    def iter_chunks(
        self, limit: int | None = None, batch_size: int = 256
    ) -> Iterator[ChunkRecord]:
        """컬렉션 전체를 scroll로 훑는다. 평가셋 생성의 입력으로 쓴다."""
        offset = None
        fetched = 0
        while True:
            page_size = batch_size
            if limit is not None:
                page_size = min(batch_size, limit - fetched)
                if page_size <= 0:
                    return

            points, offset = self.client.scroll(
                collection_name=self.settings.collection,
                limit=page_size,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return
            for point in points:
                yield ChunkRecord.from_payload(point.payload or {})
            fetched += len(points)
            if offset is None:
                return

    def search(
        self,
        vector: Sequence[float],
        top_k: int = 10,
        paper_ids: Sequence[str] | None = None,
    ) -> list[SearchHit]:
        """코사인 유사도 상위 `top_k`를 반환한다.

        `paper_ids`를 주면 해당 논문으로 범위를 제한한다. 선택 논문
        내부 검색(neo4j-schema.md 11.1)과 같은 동작이다.
        """
        from qdrant_client import models

        query_filter = None
        if paper_ids:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="paper_id",
                        match=models.MatchAny(any=list(paper_ids)),
                    )
                ]
            )

        # qdrant-client 1.19에서 `search`가 사라지고 `query_points`로 통합됐다.
        # 팀마다 설치된 버전이 다를 수 있으므로 둘 다 지원한다.
        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.settings.collection,
                query=list(vector),
                using=self.settings.vector_name,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )
            points = response.points
        else:  # pragma: no cover - 구버전 클라이언트
            query_vector: Any = list(vector)
            if self.settings.vector_name:
                query_vector = (self.settings.vector_name, query_vector)
            points = self.client.search(
                collection_name=self.settings.collection,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
            )

        return [
            SearchHit(
                chunk=ChunkRecord.from_payload(point.payload or {}),
                score=float(point.score),
                rank=rank,
            )
            for rank, point in enumerate(points, start=1)
        ]

    def delete_collection(self) -> None:
        if self.collection_exists():
            self.client.delete_collection(self.settings.collection)

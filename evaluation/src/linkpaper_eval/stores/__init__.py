"""데이터 저장소 어댑터.

평가 하네스가 Qdrant(벡터)와 Neo4j(그래프)에 직접 붙기 위한 얇은 래퍼다.
백엔드 패키지를 임포트하지 않는다는 평가 하네스의 원칙은 유지한다. 여기서
연결하는 대상은 백엔드 코드가 아니라 데이터이므로, 백엔드 구현과 무관하게
같은 인덱스를 대상으로 검색 품질을 잴 수 있다.

드라이버(`neo4j`, `qdrant-client`)는 선택 의존성이다. 임포트는 실제로
연결할 때까지 미루므로, 드라이버를 설치하지 않아도 이 패키지를 임포트하는
것만으로는 실패하지 않는다.
"""

from linkpaper_eval.stores.config import (
    EmbeddingSettings,
    Neo4jSettings,
    QdrantSettings,
    StoreSettings,
)
from linkpaper_eval.stores.embedding import (
    Embedder,
    HashEmbedder,
    OpenAIEmbedder,
    build_embedder,
)
from linkpaper_eval.stores.records import ChunkRecord, SearchHit, make_chunk_id

__all__ = [
    "ChunkRecord",
    "Embedder",
    "EmbeddingSettings",
    "HashEmbedder",
    "Neo4jSettings",
    "Neo4jStore",
    "OpenAIEmbedder",
    "QdrantSettings",
    "QdrantStore",
    "SearchHit",
    "StoreSettings",
    "build_embedder",
    "make_chunk_id",
]


def __getattr__(name: str):
    """드라이버가 필요한 스토어는 실제로 참조될 때 임포트한다."""
    if name == "Neo4jStore":
        from linkpaper_eval.stores.neo4j_store import Neo4jStore

        return Neo4jStore
    if name == "QdrantStore":
        from linkpaper_eval.stores.qdrant_store import QdrantStore

        return QdrantStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

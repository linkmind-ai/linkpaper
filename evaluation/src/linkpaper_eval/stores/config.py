"""저장소 접속 설정.

값의 우선순위는 `명시적 인자 > 환경변수 > 기본값`이다. 평가 설정 YAML에
비밀번호를 적지 않고도 실행할 수 있어야 하므로, 자격증명은 환경변수를
기본 경로로 삼는다. YAML에서는 `${QDRANT_URL:-http://localhost:6333}`
형태로 기존 `config._expand_env`가 처리한다.

기본 호스트를 `localhost`로 둔 것은 의도적이다. docker-compose 내부에서
실행할 때는 컨테이너 이름(`neo4j`, `qdrant`)이 맞지만, 평가는 대부분
호스트에서 CLI로 돌린다. 컨테이너 안에서 돌릴 때만 환경변수를 덮어쓰면 된다.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


class Neo4jSettings(BaseModel):
    """Neo4j 접속 정보."""

    model_config = ConfigDict(extra="ignore")

    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "linkpaper-password"
    database: str = "neo4j"
    timeout_s: float = 30.0

    @classmethod
    def from_env(cls, **overrides: Any) -> Neo4jSettings:
        base = {
            "uri": _env("NEO4J_URI", "bolt://localhost:7687"),
            "username": _env("NEO4J_USERNAME", "neo4j"),
            "password": _env("NEO4J_PASSWORD", "linkpaper-password"),
            "database": _env("NEO4J_DATABASE", "neo4j"),
        }
        base.update(_drop_none(overrides))
        return cls.model_validate(base)

    def redacted(self) -> str:
        return f"{self.uri} (user={self.username}, db={self.database})"


class QdrantSettings(BaseModel):
    """Qdrant 접속 정보.

    `vector_name`은 named vector를 쓰는 컬렉션에서만 채운다. 비워 두면
    기본(무명) 벡터를 사용한다.
    """

    model_config = ConfigDict(extra="ignore")

    url: str = "http://localhost:6333"
    api_key: str | None = None
    collection: str = "linkpaper_chunks"
    vector_name: str | None = None
    timeout_s: float = 30.0
    prefer_grpc: bool = False

    @classmethod
    def from_env(cls, **overrides: Any) -> QdrantSettings:
        base: dict[str, Any] = {
            "url": _env("QDRANT_URL", "http://localhost:6333"),
            "collection": _env("QDRANT_COLLECTION", "linkpaper_chunks"),
        }
        api_key = os.environ.get("QDRANT_API_KEY")
        if api_key:
            base["api_key"] = api_key
        vector_name = os.environ.get("QDRANT_VECTOR_NAME")
        if vector_name:
            base["vector_name"] = vector_name
        base.update(_drop_none(overrides))
        return cls.model_validate(base)

    def redacted(self) -> str:
        auth = "with api key" if self.api_key else "no api key"
        return f"{self.url} (collection={self.collection}, {auth})"


class EmbeddingSettings(BaseModel):
    """질의·청크 임베딩 설정.

    `provider: hash`는 네트워크와 API 키 없이 동작하는 결정적 임베더다.
    CI와 파이프라인 검증용이며, 품질 비교에는 `openai`를 쓴다.
    """

    model_config = ConfigDict(extra="ignore")

    provider: str = "hash"
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    batch_size: int = 64
    timeout_s: float = 60.0

    @classmethod
    def from_env(cls, **overrides: Any) -> EmbeddingSettings:
        base: dict[str, Any] = {
            "provider": _env("LINKPAPER_EMBEDDING_PROVIDER", "hash"),
            "model": _env("LINKPAPER_EMBEDDING_MODEL", "text-embedding-3-small"),
        }
        dimensions = os.environ.get("LINKPAPER_EMBEDDING_DIMENSIONS")
        if dimensions:
            base["dimensions"] = int(dimensions)
        base.update(_drop_none(overrides))
        return cls.model_validate(base)


class StoreSettings(BaseModel):
    """스토어 설정 묶음. CLI와 설정 YAML이 공유한다."""

    model_config = ConfigDict(extra="ignore")

    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> StoreSettings:
        overrides = overrides or {}
        return cls(
            neo4j=Neo4jSettings.from_env(**(overrides.get("neo4j") or {})),
            qdrant=QdrantSettings.from_env(**(overrides.get("qdrant") or {})),
            embedding=EmbeddingSettings.from_env(**(overrides.get("embedding") or {})),
        )

"""오프라인 builder의 저장소 및 모델 설정."""

from __future__ import annotations

from pydantic import AliasChoices, Field, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict


class BuilderSettings(BaseSettings):
    """환경변수로 덮어쓸 수 있는 Neo4j·Qdrant·임베딩 설정."""

    neo4j_uri: str = Field(
        "bolt://localhost:7687",
        validation_alias=AliasChoices("NEO4J_URI", "INDEXING_NEO4J_URI"),
    )
    neo4j_username: str = Field("neo4j", validation_alias="NEO4J_USERNAME")
    neo4j_password: str = Field("linkpaper-password", validation_alias="NEO4J_PASSWORD")
    neo4j_database: str = Field("neo4j", validation_alias="NEO4J_DATABASE")

    qdrant_url: str = Field("http://localhost:6333", validation_alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(None, validation_alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(
        "linkpaper_chunks_v1", validation_alias="QDRANT_COLLECTION"
    )

    embedding_provider: str = Field(
        "hash", validation_alias="LINKPAPER_EMBEDDING_PROVIDER"
    )
    embedding_model: str = Field(
        "text-embedding-3-small", validation_alias="LINKPAPER_EMBEDDING_MODEL"
    )
    embedding_dimensions: PositiveInt = Field(
        1536, validation_alias="LINKPAPER_EMBEDDING_DIMENSIONS"
    )
    embedding_base_url: str = Field(
        "https://api.openai.com/v1",
        validation_alias="LINKPAPER_EMBEDDING_BASE_URL",
    )
    embedding_batch_size: PositiveInt = Field(
        64, validation_alias="LINKPAPER_EMBEDDING_BATCH_SIZE"
    )
    embedding_version: str = Field("v1", validation_alias="LINKPAPER_EMBEDDING_VERSION")

    schema_version: str = Field("v1", validation_alias="LINKPAPER_SCHEMA_VERSION")
    qdrant_batch_size: PositiveInt = Field(128, validation_alias="QDRANT_BATCH_SIZE")
    include_reference_chunks: bool = Field(
        False, validation_alias="INDEXING_INCLUDE_REFERENCE_CHUNKS"
    )

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

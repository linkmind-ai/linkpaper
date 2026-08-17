from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LinkPaper API"
    environment: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-5.6-luna"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "linkpaper-password"
    neo4j_database: str = "neo4j"

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "linkpaper_chunks_openai_3_large_1536_v1"

    # 온라인 질의 벡터도 오프라인 적재 벡터와 같은 차원을 사용해야 한다.
    linkpaper_embedding_provider: str = "openai"
    linkpaper_embedding_model: str = "text-embedding-3-large"
    linkpaper_embedding_dimensions: int = 1536
    linkpaper_embedding_version: str = "openai-3-large-1536-v1"
    linkpaper_schema_version: str = "v1"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

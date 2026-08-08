"""Data Pipeline 설정과 로깅.

값은 모두 환경변수 `INDEXING_*`로 덮어쓸 수 있다. 온라인 백엔드와 설정을
공유하지 않으므로 접두사만 다르면 같은 `.env` 파일을 써도 충돌하지 않는다.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class IndexingSettings(BaseSettings):
    # Hugging Face Papers API
    hf_base_url: str = "https://huggingface.co"
    hf_timeout_s: float = 30.0
    hf_max_retries: int = 3
    hf_backoff_s: float = 1.0
    hf_page_size: int = 50
    # 하루치 Daily Papers는 50편 안팎이다. 페이지네이션이 끝나지 않는 상황을
    # 대비한 안전장치이며 정상 동작에서는 도달하지 않는다.
    hf_max_pages: int = 100
    user_agent: str = "linkpaper-indexing/0.1"

    # 본문 확보
    pdf_timeout_s: float = 120.0
    # 이보다 짧은 Markdown 응답은 오류 페이지나 stub으로 보고 PDF로 넘어간다.
    markdown_min_chars: int = 500

    # 청킹
    chunk_size: int = 1200
    chunk_overlap: int = 150

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="INDEXING_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> IndexingSettings:
    return IndexingSettings()


settings = get_settings()


def configure_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=level or settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

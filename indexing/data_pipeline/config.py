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
    # arXiv는 요청이 몰리면 전송을 중간에 끊는다. 정확히 1MiB 경계에서 끊긴
    # 사례가 관찰됐고, 같은 주소를 잠시 뒤 다시 받으면 정상이었다.
    # 논문 사이에 최소 간격을 두고, 끊긴 다운로드는 백오프를 두고 다시 받는다.
    pdf_request_delay_s: float = 3.0
    pdf_max_retries: int = 3
    pdf_backoff_s: float = 2.0
    # PDF 변환 결과가 이보다 짧으면 본문을 못 얻은 것으로 보고 실패 처리한다.
    # 텍스트 레이어가 없는 스캔본이 빈 논문으로 인덱싱되는 것을 막는다.
    markdown_min_chars: int = 500

    # 청킹은 섹션 단위다. 길이로 자르지 않는다.
    # 길이 기준 재분할은 같은 섹션을 근거로 쓰는 청크를 여러 개로 쪼갤 뿐이고,
    # `chunk_overlap`도 논문 문단이 커서 실측 평균 24~37자에 그쳤다(설정 150).
    # 아래 값은 임베딩 토큰 한도를 넘기지 않기 위한 안전 상한이며, 여기에
    # 걸리는 섹션은 드물다(표본에서 최대 21,555자). text-embedding-3-large의
    # 한도가 8,191토큰(영문 기준 약 32,000자)이라 그보다 낮게 잡는다.
    max_chunk_chars: int = 24000
    # 부록은 인덱싱하지 않는다. 논문당 청크의 4분의 1에서 절반을 차지하는데,
    # 사용자가 읽는 논문의 레퍼런스로서의 가치는 본문에 비해 낮다.
    include_appendix: bool = False

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

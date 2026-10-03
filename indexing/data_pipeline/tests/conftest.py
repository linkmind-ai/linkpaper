from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from data_pipeline.config import IndexingSettings
from data_pipeline.models import PaperMetadata

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings() -> IndexingSettings:
    """테스트용 설정. 재시도 대기를 없애 테스트가 느려지지 않게 한다."""
    return IndexingSettings(
        hf_base_url="https://huggingface.co",
        hf_backoff_s=0.0,
        hf_page_size=2,
        markdown_min_chars=50,
        # 대기 없이 재시도 경로를 검증한다.
        pdf_request_delay_s=0.0,
        pdf_backoff_s=0.0,
    )


@pytest.fixture
def paper_markdown() -> str:
    """pymupdf4llm 변환 결과를 본뜬 논문 본문. 제목은 굵게 감싼 ATX다."""
    return (FIXTURES / "paper.md").read_text(encoding="utf-8")


@pytest.fixture
def metadata() -> PaperMetadata:
    return PaperMetadata(
        paper_id="2401.00001",
        arxiv_id="2401.00001",
        title="Section-aware Chunking",
        abstract="We study section-aware chunking.",
        authors=["Alice Kim", "Bob Lee"],
        published_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
        source_url="https://huggingface.co/papers/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )

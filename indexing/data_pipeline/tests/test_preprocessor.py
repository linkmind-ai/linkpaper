"""Preprocessor 테스트.

네트워크와 PDF 변환을 모두 주입으로 대체한다. pymupdf4llm 변환은 느리고
플랫폼 의존적이라 단위 테스트에서 실제로 돌리지 않는다.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest

from data_pipeline.exceptions import PreprocessingError
from data_pipeline.preprocessor import Preprocessor

# conftest의 markdown_min_chars(50)를 넘는 변환 결과.
CONVERTED = "# Converted\n\n" + ("body from pdf. " * 8)


def build_preprocessor(settings, handler, pdf_converter=None) -> Preprocessor:
    return Preprocessor(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        pdf_converter=pdf_converter,
    )


def pdf_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=b"%PDF-1.7\nfake pdf bytes",
        headers={"content-type": "application/pdf"},
    )


def test_pdf_is_downloaded_and_converted(settings, metadata) -> None:
    converted: list[Path] = []
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return pdf_response()

    def converter(path: Path) -> str:
        converted.append(path)
        assert path.exists(), "변환 시점에는 임시 PDF가 존재해야 한다"
        return CONVERTED

    result = build_preprocessor(settings, handler, converter).to_markdown(metadata)

    assert result.source == "pdf-pymupdf4llm"
    assert result.text == CONVERTED
    assert result.content_hash
    assert requested == ["https://arxiv.org/pdf/2401.00001"]
    # 중간 산출물을 남기지 않는다.
    assert not converted[0].exists()


def test_hugging_face_markdown_is_never_requested(settings, metadata) -> None:
    """HF `.md` 경로는 제거됐다. 다시 들어오면 이 테스트가 막는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert not request.url.path.endswith(".md"), f"예상치 못한 요청: {request.url}"
        return pdf_response()

    build_preprocessor(settings, handler, lambda path: CONVERTED).to_markdown(metadata)


def test_non_pdf_download_raises(settings, metadata) -> None:
    """arXiv가 200으로 안내 페이지를 주는 경우를 잡아낸다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>rate limited</html>")

    with pytest.raises(PreprocessingError, match="PDF가 아닌"):
        build_preprocessor(settings, handler, lambda path: "unused").to_markdown(metadata)


def test_download_error_status_raises(settings, metadata) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"unavailable")

    with pytest.raises(PreprocessingError, match="PDF 다운로드 실패"):
        build_preprocessor(settings, handler, lambda path: "unused").to_markdown(metadata)


def test_converter_failure_becomes_preprocessing_error(settings, metadata) -> None:
    def converter(path: Path) -> str:
        raise RuntimeError("mupdf exploded")

    with pytest.raises(PreprocessingError, match="PDF 변환 실패"):
        build_preprocessor(settings, lambda r: pdf_response(), converter).to_markdown(
            metadata
        )


def test_too_short_conversion_raises(settings, metadata) -> None:
    """텍스트 레이어가 없는 스캔본은 거의 빈 Markdown으로 변환된다."""
    with pytest.raises(PreprocessingError, match="너무 짧습니다"):
        build_preprocessor(
            settings, lambda r: pdf_response(), lambda path: "  \n  "
        ).to_markdown(metadata)


def test_no_pdf_url_raises(settings, metadata) -> None:
    metadata = metadata.model_copy(update={"pdf_url": None})

    with pytest.raises(PreprocessingError, match="PDF 주소가 없습니다"):
        build_preprocessor(settings, lambda r: pdf_response()).to_markdown(metadata)


def test_paper_id_with_slash_does_not_escape_temp_dir(settings, metadata) -> None:
    """구형 arXiv ID(hep-th/9901001)가 파일 경로를 벗어나면 안 된다."""
    metadata = metadata.model_copy(
        update={
            "paper_id": "hep-th/9901001",
            "pdf_url": "https://arxiv.org/pdf/hep-th/9901001",
        }
    )
    seen: list[Path] = []

    def converter(path: Path) -> str:
        seen.append(path)
        return CONVERTED

    build_preprocessor(settings, lambda r: pdf_response(), converter).to_markdown(
        metadata
    )

    assert seen[0].name == "hep-th_9901001.pdf"
    assert seen[0].parent.name.startswith("linkpaper-pdf-")


def test_truncated_download_is_retried(settings, metadata) -> None:
    """arXiv가 전송을 중간에 끊는 경우. 다시 받으면 대개 성공한다."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body",
                request=request,
            )
        return pdf_response()

    result = build_preprocessor(settings, handler, lambda path: CONVERTED).to_markdown(
        metadata
    )

    assert result.source == "pdf-pymupdf4llm"
    assert len(attempts) == 2


def test_rate_limit_html_is_retried_then_fails(settings, metadata) -> None:
    """rate limit에 걸리면 arXiv가 200으로 HTML을 준다."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(200, content=b"<html>rate limited</html>")

    with pytest.raises(PreprocessingError, match="PDF가 아닌"):
        build_preprocessor(settings, handler, lambda path: "unused").to_markdown(metadata)

    assert len(attempts) == settings.pdf_max_retries


def test_client_error_is_not_retried(settings, metadata) -> None:
    """404는 주소가 틀린 것이라 다시 받아도 같다."""
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404, content=b"not found")

    with pytest.raises(PreprocessingError, match="HTTP 404"):
        build_preprocessor(settings, handler, lambda path: "unused").to_markdown(metadata)

    assert len(attempts) == 1


def test_requests_are_spaced_by_the_configured_delay(metadata) -> None:
    """변환이 빨랐던 논문 뒤에서는 실제로 기다린다."""
    from data_pipeline.config import IndexingSettings

    spaced = IndexingSettings(markdown_min_chars=50, pdf_request_delay_s=0.2)
    preprocessor = build_preprocessor(
        spaced, lambda r: pdf_response(), lambda path: CONVERTED
    )

    start = time.monotonic()
    preprocessor.to_markdown(metadata)
    preprocessor.to_markdown(metadata)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2, "두 번째 요청은 간격만큼 기다려야 한다"

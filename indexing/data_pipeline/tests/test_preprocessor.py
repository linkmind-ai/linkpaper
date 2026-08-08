"""Preprocessor 테스트.

네트워크와 PDF 변환을 모두 주입으로 대체한다. pymupdf4llm 변환은 느리고
플랫폼 의존적이라 단위 테스트에서 실제로 돌리지 않는다.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from data_pipeline.exceptions import PreprocessingError
from data_pipeline.preprocessor import Preprocessor

HF_MARKDOWN = """Title: Sample Paper

URL Source: https://arxiv.org/html/2401.00001

Published Time: Fri, 07 Jun 2024 00:52:44 GMT

Markdown Content:
###### Abstract

""" + ("This is the real body of the paper. " * 20)

HTML_ERROR_PAGE = "<!doctype html>\n<html><head><title>404</title></head></html>" * 20


def build_preprocessor(settings, handler, pdf_converter=None) -> Preprocessor:
    return Preprocessor(
        settings,
        client=httpx.Client(
            base_url=settings.hf_base_url,
            transport=httpx.MockTransport(handler),
        ),
        pdf_converter=pdf_converter,
    )


def pdf_response() -> httpx.Response:
    return httpx.Response(
        200, content=b"%PDF-1.7\nfake pdf bytes", headers={"content-type": "application/pdf"}
    )


def test_markdown_path_strips_the_hf_header(settings, metadata) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/papers/2401.00001.md"
        return httpx.Response(
            200, text=HF_MARKDOWN, headers={"content-type": "text/markdown; charset=utf-8"}
        )

    result = build_preprocessor(settings, handler).to_markdown(metadata)

    assert result.source == "hf-markdown"
    assert result.text.startswith("###### Abstract")
    assert "URL Source:" not in result.text
    assert result.content_hash


def test_missing_markdown_falls_back_to_pdf(settings, metadata) -> None:
    converted: list[Path] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(
                404, text=HTML_ERROR_PAGE, headers={"content-type": "text/html"}
            )
        return pdf_response()

    def converter(path: Path) -> str:
        converted.append(path)
        assert path.exists(), "변환 시점에는 임시 PDF가 존재해야 한다"
        return "# Converted\n\nbody from pdf"

    result = build_preprocessor(settings, handler, converter).to_markdown(metadata)

    assert result.source == "pdf-pymupdf4llm"
    assert result.text == "# Converted\n\nbody from pdf"
    # 중간 산출물을 남기지 않는다.
    assert not converted[0].exists()


def test_html_body_with_200_status_is_rejected(settings, metadata) -> None:
    """404 대신 200으로 HTML을 주는 경우에도 Markdown으로 착각하면 안 된다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(
                200, text=HTML_ERROR_PAGE, headers={"content-type": "text/html"}
            )
        return pdf_response()

    result = build_preprocessor(settings, handler, lambda path: "pdf body").to_markdown(
        metadata
    )

    assert result.source == "pdf-pymupdf4llm"


def test_too_short_markdown_falls_back_to_pdf(settings, metadata) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(
                200, text="Markdown Content:\nstub", headers={"content-type": "text/markdown"}
            )
        return pdf_response()

    result = build_preprocessor(settings, handler, lambda path: "pdf body").to_markdown(
        metadata
    )

    assert result.source == "pdf-pymupdf4llm"


def test_non_pdf_download_raises(settings, metadata) -> None:
    """arXiv가 200으로 안내 페이지를 주는 경우를 잡아낸다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(404, text="nope")
        return httpx.Response(200, content=b"<html>rate limited</html>")

    with pytest.raises(PreprocessingError, match="PDF가 아닌"):
        build_preprocessor(settings, handler, lambda path: "unused").to_markdown(metadata)


def test_converter_failure_becomes_preprocessing_error(settings, metadata) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(404, text="nope")
        return pdf_response()

    def converter(path: Path) -> str:
        raise RuntimeError("mupdf exploded")

    with pytest.raises(PreprocessingError, match="PDF 변환 실패"):
        build_preprocessor(settings, handler, converter).to_markdown(metadata)


def test_no_pdf_url_raises(settings, metadata) -> None:
    metadata = metadata.model_copy(update={"pdf_url": None})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    with pytest.raises(PreprocessingError, match="PDF 주소도 없습니다"):
        build_preprocessor(settings, handler).to_markdown(metadata)


def test_paper_id_with_slash_does_not_escape_temp_dir(settings, metadata) -> None:
    """구형 arXiv ID(hep-th/9901001)가 파일 경로를 벗어나면 안 된다."""
    metadata = metadata.model_copy(
        update={"paper_id": "hep-th/9901001", "pdf_url": "https://arxiv.org/pdf/hep-th/9901001"}
    )
    seen: list[Path] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".md"):
            return httpx.Response(404, text="nope")
        return pdf_response()

    def converter(path: Path) -> str:
        seen.append(path)
        return "body"

    build_preprocessor(settings, handler, converter).to_markdown(metadata)

    assert seen[0].name == "hep-th_9901001.pdf"
    assert seen[0].parent.name.startswith("linkpaper-pdf-")

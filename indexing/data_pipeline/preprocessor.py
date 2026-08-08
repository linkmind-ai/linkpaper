"""논문 본문을 Markdown으로 확보한다.

순서는 두 단계다.

1. `https://huggingface.co/papers/{paper_id}.md` 를 먼저 시도한다. HF가 arXiv
   HTML을 변환해 주므로 PDF 파싱보다 결과가 깨끗하다.
2. 유효한 Markdown이 아니면 PDF를 임시 파일로 내려받아 pymupdf4llm으로
   변환한다.

없는 논문의 `.md` 주소는 404와 함께 HTML 오류 페이지를 돌려준다. 상태 코드만
믿으면 HTML 본문을 Markdown으로 착각하므로 content-type과 본문 형태를 함께
확인한다.

PDF와 Markdown 중간 결과물은 저장하지 않는다. PDF는 변환 직후 삭제되는 임시
디렉터리에만 존재한다.
"""

from __future__ import annotations

import logging
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx

from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.exceptions import PreprocessingError
from data_pipeline.models import PaperMarkdown, PaperMetadata

logger = logging.getLogger(__name__)

MARKDOWN_PATH = "/papers/{paper_id}.md"

# HF Markdown 응답 앞부분에 붙는 머리말. 본문은 이 표시 뒤부터다.
_CONTENT_MARKER = "Markdown Content:"
_HTML_PREFIXES = ("<!doctype", "<html", "<?xml")
_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")

PdfConverter = Callable[[Path], str]


def pymupdf4llm_to_markdown(pdf_path: Path) -> str:
    """pymupdf4llm 변환. import가 무겁고 네이티브 의존성이 있어 지연 로딩한다."""
    try:
        import pymupdf4llm
    except ImportError as exc:  # pragma: no cover - 설치 환경 문제
        raise PreprocessingError(
            "pymupdf4llm이 설치되어 있지 않습니다. indexing에서 pip install -e '.[dev]'를 실행하세요."
        ) from exc
    return pymupdf4llm.to_markdown(str(pdf_path))


class Preprocessor:
    """논문 PDF/Markdown을 정규화된 Markdown 하나로 만든다.

    `client`와 `pdf_converter`를 주입하면 네트워크와 PDF 변환 없이 테스트할 수
    있다. 둘 다 느리고 불안정한 경계라 기본 구현을 밖에서 갈아끼울 수 있게 뒀다.
    """

    def __init__(
        self,
        settings: IndexingSettings | None = None,
        client: httpx.Client | None = None,
        pdf_converter: PdfConverter | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.settings.hf_base_url,
            timeout=self.settings.hf_timeout_s,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )
        self.pdf_converter = pdf_converter or pymupdf4llm_to_markdown

    def to_markdown(self, metadata: PaperMetadata) -> PaperMarkdown:
        text = self._fetch_hf_markdown(metadata.paper_id)
        if text is not None:
            return PaperMarkdown(
                paper_id=metadata.paper_id, text=text, source="hf-markdown"
            )

        logger.info(
            "HF Markdown을 쓸 수 없어 PDF로 전환합니다 paper_id=%s", metadata.paper_id
        )
        return PaperMarkdown(
            paper_id=metadata.paper_id,
            text=self._convert_pdf(metadata),
            source="pdf-pymupdf4llm",
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    # ------------------------------------------------------------------
    # 1단계: HF Markdown
    # ------------------------------------------------------------------
    def _fetch_hf_markdown(self, paper_id: str) -> str | None:
        """유효한 Markdown이면 본문을, 아니면 `None`을 돌려준다.

        여기서 예외를 던지지 않는 이유는 실패가 곧 PDF 경로로의 정상적인
        분기이기 때문이다.
        """
        path = MARKDOWN_PATH.format(paper_id=paper_id)
        try:
            response = self.client.get(path)
        except httpx.HTTPError as exc:
            logger.warning("Markdown 요청 실패 paper_id=%s error=%s", paper_id, exc)
            return None

        if response.status_code >= 400:
            logger.info(
                "Markdown 응답 없음 paper_id=%s status=%d", paper_id, response.status_code
            )
            return None

        content_type = response.headers.get("content-type", "")
        if "html" in content_type.lower():
            logger.info(
                "Markdown이 아닌 응답 paper_id=%s content-type=%s", paper_id, content_type
            )
            return None

        text = _strip_hf_header(response.text)
        if not _looks_like_markdown(text, self.settings.markdown_min_chars):
            logger.info("Markdown 본문이 유효하지 않음 paper_id=%s", paper_id)
            return None

        logger.debug("HF Markdown 확보 paper_id=%s chars=%d", paper_id, len(text))
        return text

    # ------------------------------------------------------------------
    # 2단계: PDF → Markdown
    # ------------------------------------------------------------------
    def _convert_pdf(self, metadata: PaperMetadata) -> str:
        if not metadata.pdf_url:
            raise PreprocessingError(
                f"{metadata.paper_id}: Markdown을 받지 못했고 PDF 주소도 없습니다"
            )

        with tempfile.TemporaryDirectory(prefix="linkpaper-pdf-") as tmp_dir:
            # paper_id에 '/'가 들어가는 구형 arXiv ID가 있으므로 파일명을 정규화한다.
            safe_name = _UNSAFE_FILENAME_RE.sub("_", metadata.paper_id) or "paper"
            pdf_path = Path(tmp_dir) / f"{safe_name}.pdf"
            self._download_pdf(metadata.pdf_url, pdf_path)

            try:
                text = self.pdf_converter(pdf_path)
            except PreprocessingError:
                raise
            except Exception as exc:
                raise PreprocessingError(
                    f"{metadata.paper_id}: PDF 변환 실패 - {type(exc).__name__}: {exc}"
                ) from exc

        if not text or not text.strip():
            raise PreprocessingError(f"{metadata.paper_id}: PDF 변환 결과가 비어 있습니다")

        logger.debug("PDF 변환 완료 paper_id=%s chars=%d", metadata.paper_id, len(text))
        return text

    def _download_pdf(self, pdf_url: str, destination: Path) -> None:
        try:
            with self.client.stream(
                "GET", pdf_url, timeout=self.settings.pdf_timeout_s
            ) as response:
                if response.status_code >= 400:
                    raise PreprocessingError(
                        f"PDF 다운로드 실패 {pdf_url} - HTTP {response.status_code}"
                    )
                with destination.open("wb") as handle:
                    for block in response.iter_bytes():
                        handle.write(block)
        except httpx.HTTPError as exc:
            raise PreprocessingError(
                f"PDF 다운로드 실패 {pdf_url} - {type(exc).__name__}: {exc}"
            ) from exc

        # arXiv는 점검 중이거나 rate limit에 걸리면 200으로 HTML을 준다.
        with destination.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise PreprocessingError(f"PDF가 아닌 응답입니다: {pdf_url}")


def _strip_hf_header(text: str) -> str:
    """`Title:` / `URL Source:` 로 시작하는 HF 머리말을 떼어낸다."""
    marker = text.find(_CONTENT_MARKER)
    if marker == -1:
        return text.strip()
    return text[marker + len(_CONTENT_MARKER) :].strip()


def _looks_like_markdown(text: str, min_chars: int) -> bool:
    stripped = text.strip()
    if len(stripped) < min_chars:
        return False
    return not stripped[:200].lower().lstrip().startswith(_HTML_PREFIXES)

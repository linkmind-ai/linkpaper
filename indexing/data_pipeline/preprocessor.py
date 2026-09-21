"""논문 본문을 Markdown으로 확보한다.

arXiv PDF를 내려받아 pymupdf4llm으로 변환한다. 경로는 이것 하나뿐이다.

한때 `https://huggingface.co/papers/{paper_id}.md` 를 먼저 시도했다. HF가 arXiv
HTML을 변환해 주므로 PDF 파싱보다 깨끗할 것으로 봤지만 실측 결과는 반대였다.
Daily Papers 25편 표본에서 10편은 `.md` 가 아예 없었고(404), Markdown을 받은
15편 중 11편은 ATX 제목이 하나도 없어 논문 전체가 단일 섹션이 됐다. 제목이
살아 있는 논문은 4편뿐이라 Chunker의 섹션 인식이 사실상 놀고 있었다.

수식이 제목으로 둔갑하기도 했다. arXiv HTML 변환본은 수식을 토큰마다 줄바꿈해
내는데, `=` 한 글자만 있는 줄이 setext 밑줄로 인식돼 바로 윗줄의 `𝐿`이 제목이
됐다(2608.05042). 그 논문의 섹션 17개가 전부 수식 조각이었다.

같은 논문을 PDF로 변환하면 실제 섹션 구조가 복원된다. 비용은 편당 10초
안팎(다운로드 + 변환)이고, 한 달치 배치에서 PDF 확보 실패는 1건이었다.

PDF와 Markdown 중간 결과물은 저장하지 않는다. PDF는 변환 직후 삭제되는 임시
디렉터리에만 존재한다.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.exceptions import PreprocessingError
from data_pipeline.models import PaperMarkdown, PaperMetadata

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")

PdfConverter = Callable[[Path], str]

# 429/5xx, 전송 중단, rate limit HTML처럼 다시 받으면 될 가능성이 있는 실패.
_RETRYABLE_STATUS = {429}


class _TransientDownloadError(Exception):
    """다시 시도할 가치가 있는 다운로드 실패."""


def pymupdf4llm_to_markdown(pdf_path: Path) -> str:
    """pymupdf4llm 변환. import가 무겁고 네이티브 의존성이 있어 지연 로딩한다."""
    try:
        import pymupdf4llm
    except ImportError as exc:  # pragma: no cover - 설치 환경 문제
        raise PreprocessingError(
            "pymupdf4llm이 설치되어 있지 않습니다. indexing에서 pip install -e '.[dev]'를 실행하세요."
        ) from exc

    with _stdout_to_stderr():
        return pymupdf4llm.to_markdown(str(pdf_path))


@contextlib.contextmanager
def _stdout_to_stderr():
    """변환 중 표준출력에 나가는 것을 표준오류로 돌린다.

    pymupdf4llm은 파서 경고와 OCR 진행 상황을 찍는데, CLI의 `--json` 출력이
    표준출력이라 그대로 두면 JSON이 깨진다. MuPDF가 네이티브 레벨에서 쓰므로
    `contextlib.redirect_stdout`으로는 잡히지 않아 파일 디스크립터를 바꾼다.
    """
    sys.stdout.flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


class Preprocessor:
    """논문 PDF를 정규화된 Markdown 하나로 만든다.

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
        # PDF 주소는 절대 URL(arxiv.org)이라 base_url을 두지 않는다.
        self.client = client or httpx.Client(
            timeout=self.settings.hf_timeout_s,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )
        self.pdf_converter = pdf_converter or pymupdf4llm_to_markdown
        self._last_request_at: float | None = None

    def to_markdown(self, metadata: PaperMetadata) -> PaperMarkdown:
        return PaperMarkdown(
            paper_id=metadata.paper_id,
            text=self._convert_pdf(metadata),
            source="pdf-pymupdf4llm",
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _convert_pdf(self, metadata: PaperMetadata) -> str:
        if not metadata.pdf_url:
            raise PreprocessingError(f"{metadata.paper_id}: PDF 주소가 없습니다")

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

        # 스캔본처럼 텍스트 레이어가 없는 PDF는 변환 결과가 거의 비어 나온다.
        # 그대로 두면 본문 없는 논문이 청크 몇 개로 인덱싱된다.
        stripped = text.strip() if text else ""
        if len(stripped) < self.settings.markdown_min_chars:
            raise PreprocessingError(
                f"{metadata.paper_id}: PDF 변환 결과가 너무 짧습니다 "
                f"({len(stripped)}자 < {self.settings.markdown_min_chars}자)"
            )

        logger.debug("PDF 변환 완료 paper_id=%s chars=%d", metadata.paper_id, len(text))
        return text

    def _download_pdf(self, pdf_url: str, destination: Path) -> None:
        last_error = ""
        for attempt in range(1, self.settings.pdf_max_retries + 1):
            self._throttle()
            try:
                self._download_once(pdf_url, destination)
            except _TransientDownloadError as exc:
                last_error = str(exc)
            else:
                return

            if attempt < self.settings.pdf_max_retries:
                delay = self.settings.pdf_backoff_s * (2 ** (attempt - 1))
                logger.warning(
                    "PDF 다운로드 재시도 %d/%d url=%s delay=%.1fs error=%s",
                    attempt,
                    self.settings.pdf_max_retries,
                    pdf_url,
                    delay,
                    last_error,
                )
                if delay > 0:
                    time.sleep(delay)

        raise PreprocessingError(f"PDF 다운로드 실패 {pdf_url} - {last_error}")

    def _throttle(self) -> None:
        """arXiv 요청 사이에 최소 간격을 둔다.

        PDF 변환이 논문당 5~25초씩 걸려서 대개는 저절로 간격이 생긴다. 변환이
        빨랐던 논문 뒤에서만 실제로 기다리므로 배치 전체 시간에는 거의 영향이
        없으면서 요청이 몰리는 구간만 눌러 준다.
        """
        delay = self.settings.pdf_request_delay_s
        if delay > 0 and self._last_request_at is not None:
            waited = time.monotonic() - self._last_request_at
            if waited < delay:
                time.sleep(delay - waited)
        self._last_request_at = time.monotonic()

    def _download_once(self, pdf_url: str, destination: Path) -> None:
        try:
            with self.client.stream(
                "GET", pdf_url, timeout=self.settings.pdf_timeout_s
            ) as response:
                if response.status_code >= 400:
                    message = f"HTTP {response.status_code}"
                    # 4xx는 주소 자체가 틀린 경우라 다시 받아도 결과가 같다.
                    if (
                        response.status_code >= 500
                        or response.status_code in _RETRYABLE_STATUS
                    ):
                        raise _TransientDownloadError(message)
                    raise PreprocessingError(f"PDF 다운로드 실패 {pdf_url} - {message}")
                with destination.open("wb") as handle:
                    for block in response.iter_bytes():
                        handle.write(block)
        except httpx.HTTPError as exc:
            # 전송이 중간에 끊긴 경우가 여기로 온다. 받다 만 파일은 다음 시도의
            # `open("wb")`가 덮어쓴다.
            raise _TransientDownloadError(f"{type(exc).__name__}: {exc}") from exc

        # arXiv는 점검 중이거나 rate limit에 걸리면 200으로 HTML을 준다.
        with destination.open("rb") as handle:
            if handle.read(5) != b"%PDF-":
                raise _TransientDownloadError("PDF가 아닌 응답입니다")

"""Hugging Face Papers API 클라이언트.

실제 API 동작에 맞춰 구현했다.

- `GET /api/papers/{paper_id}` 는 논문 객체를 그대로 반환한다.
- `GET /api/daily_papers?date=YYYY-MM-DD&limit=&p=` 는 `{"paper": {...}}` 로
  한 번 감싼 항목의 배열을 반환한다. `date`는 완전한 ISO 날짜만 받는다.
  월 단위(`2026-07`)를 넘기면 400이므로 기간 조회는 날짜를 하루씩 돌린다.
- 페이지네이션은 `p`(0부터)와 `limit`을 쓰고, 다음 페이지가 있으면 응답
  헤더에 `Link: <...>; rel="next"` 가 붙는다. 범위를 넘긴 페이지는 빈 배열이다.

베이스 구축(이번 달 전체)과 Daily Papers 최신화(특정 날짜)가 같은 조회
경로를 공유한다.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from data_pipeline.config import IndexingSettings, settings as default_settings
from data_pipeline.exceptions import PaperFetchError
from data_pipeline.models import PaperMetadata

logger = logging.getLogger(__name__)

DAILY_PAPERS_PATH = "/api/daily_papers"
PAPER_PATH = "/api/papers/{paper_id}"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"

# HF Papers ID는 arXiv base ID다. 형식이 맞을 때만 arXiv 식별자로 취급한다.
_ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}$")
_NEXT_LINK_RE = re.compile(r'rel="next"')
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HuggingFacePapersClient:
    """논문 메타데이터 조회 담당.

    `client`를 주입하면 외부 호출 없이 테스트할 수 있다.
    """

    def __init__(
        self,
        settings: IndexingSettings | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or default_settings
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.settings.hf_base_url,
            timeout=self.settings.hf_timeout_s,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def get_paper(self, paper_id: str) -> PaperMetadata:
        """논문 한 편의 메타데이터를 가져온다."""
        payload, _ = self._get_json(PAPER_PATH.format(paper_id=paper_id))
        if not isinstance(payload, dict):
            raise PaperFetchError(f"Unexpected paper payload for {paper_id}")
        return self._to_metadata(payload)

    def list_daily_papers(self, day: date | None = None) -> list[PaperMetadata]:
        """특정 날짜의 Daily Papers 전체를 가져온다. 기본값은 오늘이다."""
        day = day or date.today()
        params = {"date": day.isoformat()}
        papers = [
            self._to_metadata(item)
            for page in self._iter_pages(params)
            for item in page
        ]
        logger.info("Daily Papers 조회 date=%s count=%d", day.isoformat(), len(papers))
        return papers

    def list_papers_between(self, start: date, end: date) -> list[PaperMetadata]:
        """`start`부터 `end`까지(양끝 포함)의 논문을 모은다.

        API가 하루 단위 조회만 지원하므로 날짜를 돌면서 합친다. 하루가
        실패해도 나머지 날짜는 계속 수집한다. 베이스 구축이 중간의 일시적인
        오류 하나로 통째로 멈추면 안 되기 때문이다.
        """
        if start > end:
            raise ValueError(f"start({start})가 end({end})보다 늦습니다")

        collected: dict[str, PaperMetadata] = {}
        failed_days: list[str] = []

        day = start
        while day <= end:
            try:
                for paper in self.list_daily_papers(day):
                    # 같은 논문이 여러 날에 걸쳐 올라오는 경우가 있어 중복을 제거한다.
                    collected.setdefault(paper.paper_id, paper)
            except (PaperFetchError, httpx.HTTPError) as exc:
                failed_days.append(day.isoformat())
                logger.warning("Daily Papers 조회 실패 date=%s error=%s", day, exc)
            day += timedelta(days=1)

        if failed_days:
            logger.warning(
                "조회하지 못한 날짜 %d일: %s", len(failed_days), ", ".join(failed_days)
            )
        logger.info(
            "기간 조회 완료 %s~%s papers=%d", start, end, len(collected)
        )
        return list(collected.values())

    def list_papers_in_month(
        self, year: int | None = None, month: int | None = None
    ) -> list[PaperMetadata]:
        """해당 월의 논문 전체. 기본값은 이번 달이며 오늘까지만 조회한다."""
        today = date.today()
        year = year or today.year
        month = month or today.month

        start = date(year, month, 1)
        end = _last_day_of_month(year, month)
        if end > today:
            end = today
        if start > today:
            return []
        return self.list_papers_between(start, end)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _iter_pages(self, params: dict[str, Any]) -> Iterator[list[dict[str, Any]]]:
        for page in range(self.settings.hf_max_pages):
            payload, headers = self._get_json(
                DAILY_PAPERS_PATH,
                params={**params, "p": page, "limit": self.settings.hf_page_size},
            )
            if not isinstance(payload, list):
                raise PaperFetchError(f"Unexpected daily papers payload: {type(payload)}")
            if not payload:
                return
            yield payload
            if not _NEXT_LINK_RE.search(headers.get("link", "")):
                return
        logger.warning("페이지 한도 %d에 도달했습니다: %s", self.settings.hf_max_pages, params)

    def _get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> tuple[Any, httpx.Headers]:
        """재시도가 붙은 GET. 4xx는 즉시 실패, 429/5xx와 전송 오류만 재시도한다."""
        last_error: str = ""
        for attempt in range(1, self.settings.hf_max_retries + 1):
            try:
                response = self.client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code < 400:
                    try:
                        return response.json(), response.headers
                    except ValueError as exc:
                        raise PaperFetchError(f"GET {path} 응답이 JSON이 아닙니다: {exc}") from exc
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                if response.status_code not in _RETRYABLE_STATUS:
                    raise PaperFetchError(f"GET {path} 실패 - {last_error}")

            if attempt < self.settings.hf_max_retries:
                delay = self.settings.hf_backoff_s * (2 ** (attempt - 1))
                logger.warning(
                    "재시도 %d/%d path=%s delay=%.1fs error=%s",
                    attempt,
                    self.settings.hf_max_retries,
                    path,
                    delay,
                    last_error,
                )
                time.sleep(delay)

        raise PaperFetchError(f"GET {path} 실패 - {last_error}")

    # ------------------------------------------------------------------
    # 파싱
    # ------------------------------------------------------------------
    def _to_metadata(self, payload: dict[str, Any]) -> PaperMetadata:
        """단건 조회와 Daily Papers 목록의 두 응답 형태를 모두 받는다."""
        paper = payload.get("paper") if isinstance(payload.get("paper"), dict) else payload

        paper_id = str(paper.get("id") or "").strip()
        if not paper_id:
            raise PaperFetchError(f"paper id가 없습니다: {list(payload)[:5]}")

        arxiv_id = paper_id if _ARXIV_ID_RE.match(paper_id) else None

        return PaperMetadata(
            paper_id=paper_id,
            arxiv_id=arxiv_id,
            title=str(paper.get("title") or payload.get("title") or "").strip(),
            abstract=str(paper.get("summary") or payload.get("summary") or "").strip(),
            authors=[
                str(author["name"]).strip()
                for author in paper.get("authors") or []
                if isinstance(author, dict) and author.get("name")
            ],
            keywords=[str(keyword) for keyword in paper.get("ai_keywords") or []],
            published_at=_parse_datetime(
                paper.get("publishedAt") or payload.get("publishedAt")
            ),
            source_url=f"{self.settings.hf_base_url.rstrip('/')}/papers/{paper_id}",
            pdf_url=ARXIV_PDF_URL.format(arxiv_id=arxiv_id) if arxiv_id else None,
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.debug("publishedAt 파싱 실패: %s", value)
        return None


def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)

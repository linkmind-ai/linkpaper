"""Hugging Face Papers Client 테스트.

외부 API를 호출하지 않도록 `httpx.MockTransport`로 응답을 고정한다.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from data_pipeline.exceptions import PaperFetchError
from data_pipeline.hf_client import HuggingFacePapersClient


def build_client(settings, handler) -> HuggingFacePapersClient:
    return HuggingFacePapersClient(
        settings,
        client=httpx.Client(
            base_url=settings.hf_base_url,
            transport=httpx.MockTransport(handler),
        ),
    )


def paper_payload(paper_id: str) -> dict:
    return {
        "id": paper_id,
        "title": f"Paper {paper_id}",
        "summary": "An abstract.",
        "authors": [{"name": "Alice Kim"}, {"name": "Bob Lee"}, {"hidden": True}],
        "publishedAt": "2026-08-02T00:00:00.000Z",
        "ai_keywords": ["chunking", "retrieval"],
    }


def test_get_paper_parses_flat_payload(settings) -> None:
    client = build_client(
        settings,
        lambda request: httpx.Response(200, json=paper_payload("2406.04093")),
    )

    metadata = client.get_paper("2406.04093")

    assert metadata.paper_id == "2406.04093"
    assert metadata.arxiv_id == "2406.04093"
    assert metadata.title == "Paper 2406.04093"
    assert metadata.authors == ["Alice Kim", "Bob Lee"]
    assert metadata.keywords == ["chunking", "retrieval"]
    assert metadata.published_at is not None
    assert metadata.source_url == "https://huggingface.co/papers/2406.04093"
    assert metadata.pdf_url == "https://arxiv.org/pdf/2406.04093"


def test_daily_papers_unwraps_list_payload_and_paginates(settings) -> None:
    """Daily Papers 항목은 `{"paper": {...}}` 로 감싸여 오고, 다음 페이지는
    `Link: ...; rel="next"` 헤더로 알려준다."""
    pages = {
        "0": [{"paper": paper_payload("2601.00001")}, {"paper": paper_payload("2601.00002")}],
        "1": [{"paper": paper_payload("2601.00003")}],
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["p"]
        requested.append(page)
        headers = {"link": '<https://huggingface.co/next>; rel="next"'} if page == "0" else {}
        return httpx.Response(200, json=pages.get(page, []), headers=headers)

    papers = build_client(settings, handler).list_daily_papers(date(2026, 1, 5))

    assert [paper.paper_id for paper in papers] == [
        "2601.00001",
        "2601.00002",
        "2601.00003",
    ]
    assert requested == ["0", "1"]


def test_pagination_stops_on_empty_page(settings) -> None:
    """마지막 페이지에도 next 링크가 붙어 있는 경우가 있어 빈 응답에서도 멈춘다."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["p"]
        body = [{"paper": paper_payload("2601.00001")}] if page == "0" else []
        return httpx.Response(
            200, json=body, headers={"link": '<https://x>; rel="next"'}
        )

    papers = build_client(settings, handler).list_daily_papers(date(2026, 1, 5))

    assert len(papers) == 1


def test_retries_transient_failure_then_succeeds(settings) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=paper_payload("2406.04093"))

    metadata = build_client(settings, handler).get_paper("2406.04093")

    assert metadata.paper_id == "2406.04093"
    assert len(attempts) == 3


def test_client_error_is_not_retried(settings) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(404, text="not found")

    with pytest.raises(PaperFetchError):
        build_client(settings, handler).get_paper("does-not-exist")

    assert len(attempts) == 1


def test_range_query_deduplicates_and_survives_a_failing_day(settings) -> None:
    """하루가 실패해도 나머지 날짜는 계속 수집해야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        day = request.url.params["date"]
        if day == "2026-01-02":
            return httpx.Response(500, text="boom")
        if day == "2026-01-03":
            # 앞 날짜와 같은 논문이 다시 올라온 상황
            return httpx.Response(200, json=[{"paper": paper_payload("2601.00001")}])
        return httpx.Response(200, json=[{"paper": paper_payload("2601.00001")}])

    papers = build_client(settings, handler).list_papers_between(
        date(2026, 1, 1), date(2026, 1, 3)
    )

    assert [paper.paper_id for paper in papers] == ["2601.00001"]


def test_month_query_does_not_look_past_today(settings, monkeypatch) -> None:
    queried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queried.append(request.url.params["date"])
        return httpx.Response(200, json=[])

    client = build_client(settings, handler)
    monkeypatch.setattr("data_pipeline.hf_client.date", _FrozenDate)

    client.list_papers_in_month(2026, 8)

    assert queried == ["2026-08-01", "2026-08-02", "2026-08-03"]


def test_non_arxiv_paper_id_has_no_pdf_url(settings) -> None:
    payload = paper_payload("some-hf-only-id")
    client = build_client(settings, lambda request: httpx.Response(200, json=payload))

    metadata = client.get_paper("some-hf-only-id")

    assert metadata.arxiv_id is None
    assert metadata.pdf_url is None


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return date(2026, 8, 3)

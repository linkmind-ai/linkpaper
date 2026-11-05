import asyncio

import httpx
from fastapi.testclient import TestClient

from linkpaper.adapters.papers import HuggingFacePapersClient
from linkpaper.api.dependencies import get_paper_service
from linkpaper.main import app
from linkpaper.modules.papers import PaperService

SEARCH_ITEM = {
    "paper": {
        "id": "1706.03762",
        "title": "Attention Is All You Need",
        "summary": "Transformer",
        "publishedAt": "2017-06-12T17:57:34.000Z",
        "authors": [{"name": name} for name in ("A", "B", "C", "D")],
        "ai_keywords": ["attention", "transformer", "bleu", "wmt"],
    }
}


class FakePaperSource:
    def __init__(self, *, error=None):
        self.calls = []
        self.error = error

    async def search(self, query, limit):
        self.calls.append(("search", query, limit))
        if self.error:
            raise self.error
        return [SEARCH_ITEM, {"paper": {"title": "ID가 없는 항목"}}]

    async def list_daily(self, limit):
        self.calls.append(("daily", limit))
        return [{"paper": {"id": "hf-paper", "title": "Daily"}}]


def search_with(source, query):
    app.dependency_overrides[get_paper_service] = lambda: PaperService(source)
    try:
        return TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/papers/search", params={"q": query}
        )
    finally:
        app.dependency_overrides.clear()


def test_search_returns_frontend_contract() -> None:
    source = FakePaperSource()

    response = search_with(source, " attention ")

    assert response.status_code == 200
    assert source.calls == [("search", "attention", 20)]
    assert response.json() == [
        {
            "id": "1706.03762",
            "title": "Attention Is All You Need",
            "authors": "A, B, C et al.",
            "year": 2017,
            "categories": ["attention", "transformer", "bleu"],
            "summary": "Transformer",
            "pdfUrl": "https://arxiv.org/pdf/1706.03762",
            "arxivUrl": "https://arxiv.org/abs/1706.03762",
        }
    ]


def test_empty_query_returns_daily_papers_without_arxiv_links() -> None:
    source = FakePaperSource()

    paper = search_with(source, "   ").json()[0]

    assert source.calls == [("daily", 20)]
    assert paper["id"] == "hf-paper"
    assert paper["pdfUrl"] is None
    assert paper["arxivUrl"] is None


def test_upstream_failure_returns_502() -> None:
    source = FakePaperSource(error=httpx.ConnectError("down"))

    response = search_with(source, "attention")

    assert response.status_code == 502


def test_client_uses_hugging_face_search_endpoint() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[SEARCH_ITEM])

    async def run():
        async with httpx.AsyncClient(
            base_url="https://huggingface.co",
            transport=httpx.MockTransport(handler),
        ) as http_client:
            client = HuggingFacePapersClient(client=http_client)
            return await client.search("attention", 5)

    assert asyncio.run(run()) == [SEARCH_ITEM]
    assert requests[0].url.path == "/api/papers/search"
    assert dict(requests[0].url.params) == {"q": "attention", "limit": "5"}

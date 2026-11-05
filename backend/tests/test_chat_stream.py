import json

import pytest
from fastapi.testclient import TestClient

from linkpaper.api.dependencies import get_question_answering_pipeline
from linkpaper.main import app
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.online_retrieval import RetrievedChunk
from linkpaper.pipelines.question_answering import QuestionAnsweringPipeline


class FakeOpenAIClient:
    async def stream_text(self, messages):
        yield "테스트 답변"


class FakeOnlineRetrievalService:
    async def search(self, paper_id, query):
        return [
            RetrievedChunk(
                chunk_id=f"{paper_id}:online:0:test",
                paper_id=paper_id,
                text="테스트 검색 근거",
                score=1.0,
            )
        ]


@pytest.fixture(autouse=True)
def use_fake_generation():
    pipeline = QuestionAnsweringPipeline(
        retrieval=FakeOnlineRetrievalService(),
        generation=GenerationService(client=FakeOpenAIClient()),
    )
    app.dependency_overrides[get_question_answering_pipeline] = lambda: pipeline
    yield
    app.dependency_overrides.clear()


def parse_sse(response_text: str) -> list[dict[str, object]]:
    events = []
    for block in response_text.strip().split("\n\n"):
        assert block.startswith("data: ")
        events.append(json.loads(block.removeprefix("data: ")))
    return events


def test_chat_stream_contract() -> None:
    response = TestClient(app).post(
        "/api/v1/chat/stream",
        json={
            "paperId": "p-001",
            "message": "핵심 기여은?",
            "history": [
                {"id": "m-1", "role": "user", "content": "핵심 기여은?"}
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"

    events = parse_sse(response.text)
    actual_types = []
    for event in events:
        actual_types.append(event["type"])

    assert actual_types == ["token", "done"]


def test_chat_stream_rejects_empty_message() -> None:
    response = TestClient(app).post(
        "/api/v1/chat/stream",
        json={
            "paperId": "p-001",
            "message": "",
            "history": [],
        },
    )

    assert response.status_code == 422

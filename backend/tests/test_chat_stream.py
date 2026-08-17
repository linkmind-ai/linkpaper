import json

import pytest
from fastapi.testclient import TestClient

from linkpaper.api.dependencies import get_question_answering_pipeline
from linkpaper.main import app
from linkpaper.modules.conversations import ConversationService
from linkpaper.modules.generation import GenerationService
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.retrieval import RetrievalService
from linkpaper.pipelines.question_answering import QuestionAnsweringPipeline


class FakeOpenAIClient:
    async def stream_text(self, messages):
        yield "테스트 답변"


@pytest.fixture(autouse=True)
def use_fake_generation():
    pipeline = QuestionAnsweringPipeline(
        conversations=ConversationService(),
        retrieval=RetrievalService(),
        knowledge_graph=KnowledgeGraphService(),
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


@pytest.mark.parametrize(
    ("mode", "expected_types"),
    [
        ("paper-qa", ["token", "done"]),
        (
            "graph-rag-qa",
            ["token", "citations", "done"],
        ),
        (
            "research-flow",
            ["token", "citations", "flow", "done"],
        ),
    ],
)
def test_chat_stream_contract(mode: str, expected_types: list[str]) -> None:
    response = TestClient(app).post(
        "/api/v1/chat/stream",
        json={
            "paperId": "p-001",
            "mode": mode,
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

    assert actual_types == expected_types


def test_chat_stream_rejects_unknown_mode() -> None:
    response = TestClient(app).post(
        "/api/v1/chat/stream",
        json={
            "paperId": "p-001",
            "mode": "unknown",
            "message": "question",
            "history": [],
        },
    )

    assert response.status_code == 422

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from linkpaper.adapters.llm import OpenAIClient
from linkpaper.core.config import Settings


@dataclass
class FakeEvent:
    type: str
    delta: str = ""


class FakeStream:
    def __init__(self, events: list[FakeEvent]) -> None:
        self.events = iter(events)

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> FakeEvent:
        try:
            return next(self.events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeResponses:
    def __init__(self, events: list[FakeEvent]) -> None:
        self.events = events
        self.request: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> FakeStream:
        self.request = kwargs
        return FakeStream(self.events)


@dataclass
class FakeEmbedding:
    index: int
    embedding: list[float]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    async def create(self, **kwargs: Any):
        self.request = kwargs
        data = [
            FakeEmbedding(index=index, embedding=[float(index), 1.0])
            for index, _ in enumerate(kwargs["input"])
        ]
        return type("EmbeddingResponse", (), {"data": data})()


class FakeSDKClient:
    def __init__(self, events: list[FakeEvent]) -> None:
        self.responses = FakeResponses(events)
        self.embeddings = FakeEmbeddings()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def test_stream_text_yields_only_text_deltas() -> None:
    sdk = FakeSDKClient(
        [
            FakeEvent("response.created"),
            FakeEvent("response.output_text.delta", "안녕"),
            FakeEvent("response.output_text.delta", "하세요"),
            FakeEvent("response.completed"),
        ]
    )
    client = OpenAIClient(
        settings=Settings(openai_chat_model="test-model"),
        sdk_client=sdk,
    )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in client.stream_text(
                [{"role": "user", "content": "인사해줘"}]
            )
        ]

    assert asyncio.run(collect()) == ["안녕", "하세요"]
    assert sdk.responses.request == {
        "model": "test-model",
        "input": [{"role": "user", "content": "인사해줘"}],
        "stream": True,
        "store": False,
    }


def test_stream_text_rejects_empty_messages() -> None:
    client = OpenAIClient(sdk_client=FakeSDKClient([]))

    async def collect() -> list[str]:
        return [chunk async for chunk in client.stream_text([])]

    with pytest.raises(ValueError, match="messages"):
        asyncio.run(collect())


def test_embed_texts_returns_vectors_in_input_order() -> None:
    sdk = FakeSDKClient([])
    settings = Settings(
        linkpaper_embedding_model="test-embedding",
        linkpaper_embedding_dimensions=2,
    )
    client = OpenAIClient(settings=settings, sdk_client=sdk)

    vectors = asyncio.run(client.embed_texts(["first", "second"]))

    assert vectors == [[0.0, 1.0], [1.0, 1.0]]
    assert sdk.embeddings.request == {
        "model": "test-embedding",
        "input": ["first", "second"],
        "dimensions": 2,
    }


def test_close_closes_initialized_sdk_client() -> None:
    sdk = FakeSDKClient([])
    client = OpenAIClient(sdk_client=sdk)

    asyncio.run(client.close())

    assert sdk.closed is True

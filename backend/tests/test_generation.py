import asyncio

from linkpaper.modules.generation import (
    GenerationMessage,
    GenerationRequest,
    GenerationService,
)


class FakeOpenAIClient:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.messages = None

    async def stream_text(self, messages):
        self.messages = messages
        for chunk in self.chunks:
            yield chunk


def test_stream_answer_builds_messages_and_returns_chunks() -> None:
    client = FakeOpenAIClient(["첫 번째", " 응답"])
    service = GenerationService(client=client)
    request = GenerationRequest(
        paper_id="1706.03762",
        question="핵심 기여는?",
        history=[GenerationMessage(role="user", content="논문을 설명해줘")],
        context="Transformer는 self-attention을 사용한다.",
    )

    async def collect() -> list[str]:
        return [chunk async for chunk in service.stream_answer(request)]

    assert asyncio.run(collect()) == ["첫 번째", " 응답"]
    assert client.messages[0]["role"] == "developer"
    assert client.messages[1] == {
        "role": "user",
        "content": "논문을 설명해줘",
    }
    assert "1706.03762" in client.messages[-1]["content"]
    assert "self-attention" in client.messages[-1]["content"]

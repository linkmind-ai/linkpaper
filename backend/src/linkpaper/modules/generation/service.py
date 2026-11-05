"""질문과 검색 근거를 모델 입력으로 구성한다."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from linkpaper.adapters.llm import InputMessage
from linkpaper.modules.generation.models import GenerationRequest

SYSTEM_PROMPT = """당신은 논문 이해를 돕는 AI 연구 도우미입니다.
한국어로 명확하고 간결하게 답변하세요.
검색 근거가 제공되면 그 내용만 사용하고, 근거가 부족하면 부족하다고 밝히세요.
존재하지 않는 논문 내용이나 인용 관계를 만들어내지 마세요."""


class TextGenerationClient(Protocol):
    def stream_text(
        self, messages: Sequence[InputMessage]
    ) -> AsyncIterator[str]: ...


class GenerationService:
    """OpenAI 호출에 필요한 메시지를 만들고 텍스트를 스트리밍한다."""

    def __init__(self, client: TextGenerationClient) -> None:
        self.client = client

    async def stream_answer(
        self,
        request: GenerationRequest,
    ) -> AsyncIterator[str]:
        messages = self._build_messages(request)
        async for text in self.client.stream_text(messages):
            yield text

    @staticmethod
    def _build_messages(request: GenerationRequest) -> list[InputMessage]:
        messages: list[InputMessage] = [
            {"role": "developer", "content": SYSTEM_PROMPT}
        ]
        messages.extend(
            {"role": item.role, "content": item.content}
            for item in request.history
        )
        messages.append(
            {
                "role": "user",
                "content": GenerationService._build_question(request),
            }
        )
        return messages

    @staticmethod
    def _build_question(request: GenerationRequest) -> str:
        parts = [
            f"선택 논문 ID: {request.paper_id}",
            f"사용자 질문: {request.question}",
        ]
        if request.context:
            parts.append(f"검색 근거:\n{request.context}")
        else:
            parts.append("검색 근거: 아직 제공되지 않음")
        return "\n\n".join(parts)

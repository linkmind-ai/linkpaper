"""SSE 채팅 API가 사용하는 최소 질의응답 파이프라인."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeAlias

from linkpaper.modules.generation import (
    GenerationMessage,
    GenerationRequest,
    GenerationService,
)
from linkpaper.modules.online_retrieval import OnlineRetrievalService, RetrievedChunk


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TokenEvent:
    text: str
    type: Literal["token"] = "token"


@dataclass(frozen=True)
class CitationsEvent:
    citations: list[dict[str, str]]
    type: Literal["citations"] = "citations"


@dataclass(frozen=True)
class FlowEvent:
    flow: list[dict[str, str]]
    type: Literal["flow"] = "flow"


@dataclass(frozen=True)
class DoneEvent:
    type: Literal["done"] = "done"


@dataclass(frozen=True)
class ErrorEvent:
    message: str
    type: Literal["error"] = "error"


PipelineEvent: TypeAlias = (
    TokenEvent | CitationsEvent | FlowEvent | DoneEvent | ErrorEvent
)


class QuestionAnsweringPipeline:
    """채팅 처리 흐름과 외부 서비스 사이의 경계를 제공한다."""

    def __init__(
        self,
        retrieval: OnlineRetrievalService,
        generation: GenerationService,
    ) -> None:
        self.retrieval = retrieval
        self.generation = generation

    async def stream(
        self,
        *,
        paper_id: str,
        message: str,
        history: list[ChatMessage],
    ) -> AsyncIterator[PipelineEvent]:
        """모델 답변을 API용 이벤트로 변환한다."""
        chunks = await self.retrieval.search(paper_id, message)
        request = GenerationRequest(
            paper_id=paper_id,
            question=message,
            history=[
                GenerationMessage(role=item.role, content=item.content)
                for item in history
            ],
            context=self._format_context(chunks),
        )

        async for text in self.generation.stream_answer(request):
            yield TokenEvent(text=text)

        yield DoneEvent()

    @staticmethod
    def _format_context(chunks: list[RetrievedChunk]) -> str | None:
        if not chunks:
            return None
        return "\n\n".join(
            f"[{chunk.chunk_id}]\n{chunk.text}" for chunk in chunks
        )

"""SSE 채팅 API가 사용하는 최소 질의응답 파이프라인."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeAlias

from linkpaper.modules.conversations import ConversationService
from linkpaper.modules.generation import (
    GenerationMessage,
    GenerationRequest,
    GenerationService,
)
from linkpaper.modules.knowledge_graph import KnowledgeGraphService
from linkpaper.modules.retrieval import RetrievalService

ChatMode: TypeAlias = Literal["paper-qa", "graph-rag-qa", "research-flow"]


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
        conversations: ConversationService,
        retrieval: RetrievalService,
        knowledge_graph: KnowledgeGraphService,
        generation: GenerationService,
    ) -> None:
        self.conversations = conversations
        self.retrieval = retrieval
        self.knowledge_graph = knowledge_graph
        self.generation = generation

    async def stream(
        self,
        *,
        paper_id: str,
        message: str,
        history: list[ChatMessage],
        mode: ChatMode | None = None,
    ) -> AsyncIterator[PipelineEvent]:
        """모델 답변을 API용 이벤트로 변환한다."""
        selected_mode = mode or self._route(message)
        request = GenerationRequest(
            paper_id=paper_id,
            question=message,
            history=[
                GenerationMessage(role=item.role, content=item.content)
                for item in history
            ],
        )

        async for text in self.generation.stream_answer(request):
            yield TokenEvent(text=text)

        if selected_mode in {"graph-rag-qa", "research-flow"}:
            yield CitationsEvent(citations=self._citations(paper_id))

        if selected_mode == "research-flow":
            yield FlowEvent(flow=self._flow())

        yield DoneEvent()

    @staticmethod
    def _route(message: str) -> ChatMode:
        normalized = message.casefold()
        flow_keywords = ("연구 흐름", "선행", "후속", "research flow")
        graph_keywords = ("관련 논문", "인용", "비교", "citation")

        if any(keyword in normalized for keyword in flow_keywords):
            return "research-flow"
        if any(keyword in normalized for keyword in graph_keywords):
            return "graph-rag-qa"
        return "paper-qa"

    @staticmethod
    def _citations(paper_id: str) -> list[dict[str, str]]:
        return [
            {
                "id": paper_id,
                "label": f"선택 논문 {paper_id}",
                "relation": "selected-paper",
            }
        ]

    @staticmethod
    def _flow() -> list[dict[str, str]]:
        return [
            {"stage": "selected", "label": "선택 논문"},
            {"stage": "related", "label": "관련 연구"},
        ]

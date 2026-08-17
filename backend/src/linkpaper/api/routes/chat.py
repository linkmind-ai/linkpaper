import json
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from linkpaper.api.dependencies import get_question_answering_pipeline
from linkpaper.pipelines.question_answering import (
    ChatMessage,
    ChatMode,
    ErrorEvent,
    PipelineEvent,
    QuestionAnsweringPipeline,
)

router = APIRouter()
logger = logging.getLogger(__name__)

QuestionAnsweringDependency = Annotated[
    QuestionAnsweringPipeline,
    Depends(get_question_answering_pipeline),
]


class ChatMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str


class ChatStreamRequest(BaseModel):
    paperId: str = Field(min_length=1)
    # 프론트엔드는 생략하고, 테스트나 내부 클라이언트는 명시할 수 있다.
    mode: ChatMode | None = None
    message: str = Field(min_length=1)
    history: list[ChatMessageRequest] = Field(default_factory=list)


def encode_sse(event: PipelineEvent) -> str:
    payload = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
    return f"data: {payload}\n\n"


def normalize_history(
    history: list[ChatMessageRequest], current_message: str
) -> list[ChatMessage]:
    """프론트엔드에서 중복해 보낸 현재 질문을 대화 기록에서 제거한다."""
    normalized: list[ChatMessage] = []
    for item in history:
        message = ChatMessage(role=item.role, content=item.content)
        normalized.append(message)

    if (
        normalized
        and normalized[-1].role == "user"
        and normalized[-1].content == current_message
    ):
        normalized.pop()
    return normalized


@router.post("/stream", response_class=StreamingResponse)
async def stream_chat(
    request: ChatStreamRequest,
    pipeline: QuestionAnsweringDependency,
) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        history = normalize_history(request.history, request.message)
        try:
            async for event in pipeline.stream(
                paper_id=request.paperId,
                mode=request.mode,
                message=request.message,
                history=history,
            ):
                yield encode_sse(event)
        except Exception:
            logger.exception("채팅 파이프라인 실패")
            error = ErrorEvent(message="답변 생성 중 오류가 발생했습니다.")
            yield encode_sse(error)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

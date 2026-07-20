from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from linkpaper.api.dependencies import get_question_answering_pipeline
from linkpaper.pipelines.question_answering import QuestionAnsweringPipeline

router = APIRouter()

QuestionAnsweringDependency = Annotated[
    QuestionAnsweringPipeline,
    Depends(get_question_answering_pipeline),
]


class CreateMessageRequest(BaseModel):
    paper_id: str
    content: str = Field(min_length=1)


@router.post("/{conversation_id}/messages")
async def create_message(
    conversation_id: str,
    request: CreateMessageRequest,
    _pipeline: QuestionAnsweringDependency,
) -> None:
    # 질의응답 파이프라인이 검색과 답변 생성을 조율하도록 연결한다.
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Conversation is not implemented yet: {conversation_id}",
    )

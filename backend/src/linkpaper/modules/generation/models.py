"""답변 생성에 사용하는 내부 데이터 모델."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class GenerationMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    paper_id: str
    question: str
    history: list[GenerationMessage] = field(default_factory=list)
    context: str | None = None

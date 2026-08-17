"""OpenAI Responses API adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, TypedDict

from linkpaper.core.config import Settings, get_settings


class InputMessage(TypedDict):
    role: Literal["developer", "system", "user", "assistant"]
    content: str


class OpenAIClient:
    """OpenAI SDK 응답을 애플리케이션용 텍스트 스트림으로 변환한다."""

    def __init__(
        self,
        settings: Settings | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._sdk_client = sdk_client

    @property
    def sdk_client(self) -> Any:
        if self._sdk_client is None:
            if not self.settings.openai_api_key:
                raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다")

            from openai import AsyncOpenAI

            self._sdk_client = AsyncOpenAI(api_key=self.settings.openai_api_key)
        return self._sdk_client

    async def stream_text(
        self,
        messages: Sequence[InputMessage],
    ) -> AsyncIterator[str]:
        """Responses API의 텍스트 delta만 순서대로 반환한다."""
        if not messages:
            raise ValueError("messages는 한 개 이상이어야 합니다")

        stream = await self.sdk_client.responses.create(
            model=self.settings.openai_chat_model,
            input=list(messages),
            stream=True,
            store=False,
        )
        async for event in stream:
            if getattr(event, "type", None) != "response.output_text.delta":
                continue
            delta = getattr(event, "delta", "")
            if delta:
                yield delta

    async def close(self) -> None:
        if self._sdk_client is not None:
            await self._sdk_client.close()
            self._sdk_client = None

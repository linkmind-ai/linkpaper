"""Hugging Face Papers에서 온라인 인덱싱용 Markdown을 읽는다."""

from __future__ import annotations

from typing import Any

import httpx

from linkpaper.core.config import Settings, get_settings

_CONTENT_MARKER = "Markdown Content:"


class HuggingFaceMarkdownClient:
    def __init__(
        self,
        settings: Settings | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.hf_base_url,
                timeout=self.settings.hf_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "LinkPaper/0.1"},
            )
        return self._client

    async def fetch(self, paper_id: str) -> str:
        response = await self.client.get(f"/papers/{paper_id}.md")
        response.raise_for_status()

        if "html" in response.headers.get("content-type", "").casefold():
            raise ValueError(f"{paper_id}: Markdown 대신 HTML을 받았습니다")

        content = self._strip_header(response.text)
        if len(content) < 100:
            raise ValueError(f"{paper_id}: Markdown 본문이 너무 짧습니다")
        return content

    @staticmethod
    def _strip_header(text: str) -> str:
        marker_index = text.find(_CONTENT_MARKER)
        if marker_index == -1:
            return text.strip()
        return text[marker_index + len(_CONTENT_MARKER) :].strip()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

"""Hugging Face Papers API에서 논문 검색 결과를 읽는다."""

from __future__ import annotations

from typing import Any

import httpx

from linkpaper.core.config import Settings, get_settings


class HuggingFacePapersClient:
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

    async def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        return await self._get_list(
            "/api/papers/search",
            {"q": query, "limit": limit},
        )

    async def list_daily(self, limit: int) -> list[dict[str, Any]]:
        return await self._get_list("/api/daily_papers", {"limit": limit})

    async def _get_list(
        self, path: str, params: dict[str, Any]
    ) -> list[dict[str, Any]]:
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"{path}: 목록 응답이 아닙니다")
        return payload

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

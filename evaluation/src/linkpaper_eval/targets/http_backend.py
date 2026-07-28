"""LinkPaper 백엔드 HTTP API를 호출하는 타깃.

백엔드가 구현되면 `--target http`로 바꾸기만 하면 동일한 지표로 평가된다.
현재 라우트는 501을 반환하므로 이 타깃은 오류율 1.0을 보고한다. 그것이
정상이며, 구현 진척을 그대로 보여주는 신호다.

기대하는 응답 계약은 docs/evaluation.md 4장에 정의되어 있다.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx

from linkpaper_eval.schemas import (
    EvalCase,
    RetrievedItem,
    TargetResponse,
    Triple,
    Usage,
)
from linkpaper_eval.targets.base import EvalTarget


class HttpBackendTarget(EvalTarget):
    name = "http_backend"

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_prefix: str = "/api/v1",
        timeout_s: float = 60.0,
        conversation_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix
        self.conversation_id = conversation_id
        self.client = httpx.Client(
            base_url=f"{self.base_url}{self.api_prefix}",
            timeout=timeout_s,
            headers=headers or {},
        )

    def run(self, case: EvalCase) -> TargetResponse:
        conversation_id = self.conversation_id or f"eval-{uuid.uuid4().hex[:12]}"
        payload = {"paper_id": case.paper_id, "content": case.question}

        started = time.perf_counter()
        try:
            response = self.client.post(
                f"/conversations/{conversation_id}/messages",
                json=payload,
            )
        except httpx.HTTPError as exc:
            elapsed = (time.perf_counter() - started) * 1000
            return TargetResponse(
                latency_ms=round(elapsed, 3),
                error=f"transport_error: {exc}",
            )

        elapsed = (time.perf_counter() - started) * 1000

        if response.status_code >= 400:
            return TargetResponse(
                latency_ms=round(elapsed, 3),
                error=f"http_{response.status_code}: {response.text[:200]}",
            )

        try:
            body = response.json()
        except ValueError as exc:
            return TargetResponse(
                latency_ms=round(elapsed, 3),
                error=f"invalid_json: {exc}",
            )

        return self._parse(body, elapsed)

    @staticmethod
    def _parse(body: dict[str, Any], elapsed_ms: float) -> TargetResponse:
        retrieved = [
            RetrievedItem(
                chunk_id=item.get("chunkId") or item.get("chunk_id", ""),
                paper_id=item.get("paperId") or item.get("paper_id"),
                text=item.get("text", ""),
                scope=item.get("scope", "unknown"),
                retrieval_source=item.get("retrievalSource")
                or item.get("retrieval_source", "unknown"),
                rank=item.get("rank"),
                score=item.get("score"),
                section=item.get("section"),
                matched_entity_ids=item.get("matchedEntityIds", []),
            )
            for item in body.get("retrieved", [])
        ]

        citations = [
            citation if isinstance(citation, str)
            else citation.get("chunkId") or citation.get("chunk_id", "")
            for citation in body.get("citations", [])
        ]

        triples = [
            Triple(
                subject=item.get("subject", ""),
                predicate=item.get("predicate", ""),
                object=item.get("object", ""),
                chunk_id=item.get("chunkId") or item.get("chunk_id"),
                confidence=item.get("confidence"),
            )
            for item in body.get("triples", [])
        ]

        usage_body = body.get("usage", {}) or {}
        usage = Usage(
            prompt_tokens=usage_body.get("promptTokens")
            or usage_body.get("prompt_tokens", 0),
            completion_tokens=usage_body.get("completionTokens")
            or usage_body.get("completion_tokens", 0),
            cost_usd=usage_body.get("costUsd") or usage_body.get("cost_usd", 0.0),
        )

        return TargetResponse(
            answer=body.get("answer", ""),
            citations=[citation for citation in citations if citation],
            retrieved=retrieved,
            scope=body.get("scope", "unknown"),
            triples=triples,
            latency_ms=round(elapsed_ms, 3),
            usage=usage,
            raw=body,
        )

    def close(self) -> None:
        self.client.close()

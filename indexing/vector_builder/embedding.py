"""Vector Builder가 사용하는 교체 가능한 임베딩 인터페이스."""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Sequence

import httpx

from indexing_common import BuilderSettings

_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)


class Embedder(ABC):
    """텍스트 batch를 고정 차원 dense vector로 변환한다."""

    provider: str
    model: str
    dimensions: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """입력 순서를 유지한 벡터 목록을 반환한다."""

    def close(self) -> None:
        """임베더가 가진 네트워크 자원을 정리한다."""


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return vector if norm == 0 else [value / norm for value in vector]


class HashEmbedder(Embedder):
    """CI와 연결 검증에만 사용하는 결정적 로컬 임베더."""

    provider = "hash"
    model = "blake2b-token-hash"

    def __init__(self, dimensions: int = 256, seed: str = "linkpaper") -> None:
        self.dimensions = dimensions
        self.seed = seed

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            counts = Counter(token.casefold() for token in _TOKEN_RE.findall(text))
            for token, count in counts.items():
                digest = hashlib.blake2b(
                    f"{self.seed}:{token}".encode(), digest_size=8
                ).digest()
                value = int.from_bytes(digest, "big")
                bucket = (value >> 1) % self.dimensions
                sign = 1.0 if value & 1 else -1.0
                vector[bucket] += sign * (1.0 + math.log(count))
            vectors.append(_normalize(vector))
        return vectors


class OpenAIEmbedder(Embedder):
    """OpenAI 호환 `/embeddings` API를 사용하는 실제 품질용 임베더."""

    provider = "openai"

    def __init__(self, settings: BuilderSettings) -> None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다")
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.client = httpx.Client(
            base_url=settings.embedding_base_url.rstrip("/"),
            timeout=60.0,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            payload: dict[str, object] = {"model": self.model, "input": batch}
            # text-embedding-3 계열은 요청 차원을 명시할 수 있다.
            if self.model.startswith("text-embedding-3"):
                payload["dimensions"] = self.dimensions
            response = self.client.post("/embeddings", json=payload)
            response.raise_for_status()
            ordered = sorted(response.json()["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in ordered)
        return vectors

    def close(self) -> None:
        self.client.close()


def build_embedder(settings: BuilderSettings) -> Embedder:
    provider = settings.embedding_provider.casefold()
    if provider in {"hash", "offline", "deterministic"}:
        # 해시 임베더는 품질 모델이 아니므로 큰 차원을 사용해도 이점이 없다.
        return HashEmbedder(dimensions=min(settings.embedding_dimensions, 512))
    if provider == "openai":
        return OpenAIEmbedder(settings)
    raise ValueError(f"지원하지 않는 embedding provider: {settings.embedding_provider}")

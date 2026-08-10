"""임베딩 백엔드.

두 가지를 제공한다.

- `HashEmbedder` — 해싱 기반 결정적 임베더. 네트워크와 API 키가 필요 없고
  같은 입력에 항상 같은 벡터를 낸다. CI에서 벡터 인덱스 경로 전체를
  실행해 보기 위한 것이며, 어휘 겹침만 반영하므로 의미 검색 품질을
  대표하지 않는다.
- `OpenAIEmbedder` — 실제 비교용. 이미 의존성에 있는 httpx만 사용하므로
  SDK를 새로 추가하지 않는다.

임베딩 모델이 바뀌면 벡터 인덱스를 다시 만들어야 한다. `signature()`를
실행 매니페스트에 남겨 두면 나중에 "어떤 임베딩으로 잰 점수인가"를
확인할 수 있다.
"""

from __future__ import annotations

import hashlib
import math
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence

from linkpaper_eval.metrics.generation import tokenize
from linkpaper_eval.stores.config import EmbeddingSettings


class Embedder(ABC):
    """텍스트를 벡터로 바꾸는 인터페이스."""

    name: str = "embedder"
    dimensions: int = 0

    link_threshold: float = 0.30
    """"관련 있음"으로 볼 코사인 유사도 하한.

    임베더마다 유사도 분포가 다르다. 학습된 임베딩은 관련 문서가 0.3~0.9에
    분포하지만, 해시 임베더는 어휘 겹침만 반영해서 같은 관계가 0.1~0.3에
    나온다. 하나의 상수를 공유하면 해시 임베더에서는 간선이 전혀 만들어지지
    않으므로, 임계값을 임베더가 직접 들고 있게 했다.
    """

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """여러 텍스트를 한 번에 임베딩한다."""

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def signature(self) -> str:
        return f"{self.name}:{self.dimensions}"

    def close(self) -> None:
        """자원 정리."""


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


class HashEmbedder(Embedder):
    """토큰 해싱 임베더.

    토큰을 `dimensions`개 버킷에 해싱하고 sublinear TF로 가중한 뒤
    L2 정규화한다. 코사인 유사도가 어휘 겹침에 비례하므로, 벡터 검색
    파이프라인이 제대로 연결됐는지 확인하는 데는 충분하다.

    의미 유사도는 재지 못한다. 이 임베더로 잰 점수를 모델 품질 근거로
    쓰면 안 된다.
    """

    name = "hash"
    link_threshold = 0.12

    def __init__(self, dimensions: int = 256, seed: str = "linkpaper") -> None:
        self.dimensions = dimensions
        self.seed = seed

    def _bucket(self, token: str) -> tuple[int, float]:
        digest = hashlib.blake2b(
            f"{self.seed}:{token}".encode("utf-8"), digest_size=8
        ).digest()
        value = int.from_bytes(digest, "big")
        # 마지막 비트로 부호를 정한다. 서로 다른 토큰이 같은 버킷에
        # 몰릴 때 무조건 더해지지 않도록 해서 충돌 편향을 줄인다.
        sign = 1.0 if value & 1 else -1.0
        return (value >> 1) % self.dimensions, sign

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            counts: dict[str, int] = {}
            for token in tokenize(text):
                counts[token] = counts.get(token, 0) + 1
            for token, count in counts.items():
                index, sign = self._bucket(token)
                vector[index] += sign * (1.0 + math.log(count))
            vectors.append(_l2_normalize(vector))
        return vectors


class OpenAIEmbedder(Embedder):
    """OpenAI 호환 `/embeddings` 엔드포인트를 사용한다."""

    name = "openai"
    link_threshold = 0.30

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        base_url: str = "https://api.openai.com/v1",
        api_key_env: str = "OPENAI_API_KEY",
        batch_size: int = 64,
        timeout_s: float = 60.0,
    ) -> None:
        import httpx

        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            raise RuntimeError(
                f"{api_key_env}가 설정되지 않았습니다. "
                "오프라인 실행에는 `provider: hash`를 사용하세요."
            )
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.client = httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            payload: dict[str, object] = {"model": self.model, "input": batch}
            # text-embedding-3 계열만 차원 축소를 지원한다. 구형 모델에
            # 이 필드를 보내면 400이 난다.
            if self.dimensions and self.model.startswith("text-embedding-3"):
                payload["dimensions"] = self.dimensions
            response = self.client.post("/embeddings", json=payload)
            response.raise_for_status()
            body = response.json()
            ordered = sorted(body["data"], key=lambda item: item["index"])
            vectors.extend([item["embedding"] for item in ordered])
        return vectors

    def signature(self) -> str:
        return f"openai:{self.model}:{self.dimensions}"

    def close(self) -> None:
        self.client.close()


def build_embedder(settings: EmbeddingSettings | dict | None = None) -> Embedder:
    """설정에서 임베더를 만든다."""
    if settings is None:
        settings = EmbeddingSettings()
    if isinstance(settings, dict):
        settings = EmbeddingSettings.model_validate(settings)

    provider = settings.provider.lower()
    if provider in {"hash", "offline", "deterministic"}:
        # 해시 임베더는 차원이 클수록 느리기만 하고 이득이 없다.
        return HashEmbedder(dimensions=min(settings.dimensions, 512))
    if provider in {"openai", "azure-openai"}:
        return OpenAIEmbedder(
            model=settings.model,
            dimensions=settings.dimensions,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            batch_size=settings.batch_size,
            timeout_s=settings.timeout_s,
        )
    raise ValueError(f"Unknown embedding provider: {settings.provider}")

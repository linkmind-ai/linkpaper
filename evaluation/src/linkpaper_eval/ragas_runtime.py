"""Optional, versioned Ragas adapters shared by generation and evaluation.

Ragas 0.3.9's TestsetGenerator and legacy metrics use BaseRagasLLM and
BaseRagasEmbeddings. The newer Instructor factories implement a different
protocol; selecting one opportunistically fails later during prompt execution.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
import os
from typing import Any

SUPPORTED_RAGAS_VERSION = "0.3.9"
INSTALL_HINT = "ragas가 설치되어 있지 않습니다. `pip install -e '.[ragas]'` 로 설치하세요."


def ragas_version() -> str | None:
    try:
        return version("ragas")
    except PackageNotFoundError:
        return None


def require_ragas() -> None:
    installed = ragas_version()
    if installed is None:
        raise RuntimeError(INSTALL_HINT)
    if installed != SUPPORTED_RAGAS_VERSION:
        raise RuntimeError(
            f"지원하는 ragas 버전은 {SUPPORTED_RAGAS_VERSION}입니다 "
            f"(설치된 버전: {installed}). `pip install -e '.[ragas]'` 로 설치하세요."
        )


def require_api_key(api_key_env: str = "OPENAI_API_KEY") -> str:
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        raise RuntimeError(
            f"{api_key_env}가 설정되지 않았습니다. ragas 기반 생성과 지표는 "
            "LLM 호출이 필요합니다. 오프라인으로 파이프라인만 확인하려면 "
            "`--engine offline`을 사용하세요."
        )
    return api_key


def build_llm(model: str = "gpt-4o-mini", **kwargs: Any) -> Any:
    """Build the adapter accepted by both TestsetGenerator and ragas.evaluate."""
    require_ragas()
    require_api_key()
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    return LangchainLLMWrapper(ChatOpenAI(model=model, **{"temperature": 0.0, **kwargs}))


def build_embeddings(model: str = "text-embedding-3-small") -> Any:
    require_ragas()
    require_api_key()
    from langchain_openai import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    return LangchainEmbeddingsWrapper(OpenAIEmbeddings(model=model))

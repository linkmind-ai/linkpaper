"""ragas 런타임 어댑터.

평가셋 생성기와 ragas 지표가 공통으로 필요로 하는 LLM·임베딩 래퍼를
한곳에서 만든다. ragas는 0.2 → 0.3 → 0.4를 거치며 래퍼 임포트 경로가
여러 번 바뀌었으므로, 알려진 경로를 순서대로 시도하고 전부 실패했을 때만
설치 안내와 함께 예외를 던진다. 버전을 하나로 못 박는 대신 실패 지점을
명확히 하는 쪽을 택했다.

ragas는 선택 의존성이다. 설치되어 있지 않아도 이 모듈을 임포트하는 것만
으로는 실패하지 않으며, `require_ragas()`를 부를 때 확인한다.
"""

from __future__ import annotations

import os
from typing import Any

INSTALL_HINT = (
    "ragas가 설치되어 있지 않습니다. `pip install -e '.[ragas]'` 로 설치하세요."
)


def ragas_version() -> str | None:
    try:
        import ragas
    except ImportError:
        return None
    return getattr(ragas, "__version__", "unknown")


def require_ragas() -> None:
    if ragas_version() is None:
        raise RuntimeError(INSTALL_HINT)


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
    """ragas가 쓰는 LLM 래퍼를 만든다."""
    require_ragas()
    require_api_key()
    errors: list[str] = []

    # 1) 최신 경로: ragas가 직접 OpenAI 클라이언트를 감싼다.
    try:
        import openai
        from ragas.llms import llm_factory

        return llm_factory(model, client=openai.OpenAI())
    except Exception as exc:  # noqa: BLE001 - 다음 경로를 시도한다
        errors.append(f"llm_factory: {type(exc).__name__}: {exc}")

    # 2) LangChain 래퍼 경로.
    try:
        from langchain_openai import ChatOpenAI
        from ragas.llms import LangchainLLMWrapper

        return LangchainLLMWrapper(ChatOpenAI(model=model, temperature=0.0, **kwargs))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"LangchainLLMWrapper: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "ragas LLM 래퍼를 만들지 못했습니다.\n  - " + "\n  - ".join(errors)
    )


def build_embeddings(model: str = "text-embedding-3-small") -> Any:
    """ragas가 쓰는 임베딩 래퍼를 만든다."""
    require_ragas()
    require_api_key()
    errors: list[str] = []

    try:
        import openai
        from ragas.embeddings import OpenAIEmbeddings

        return OpenAIEmbeddings(client=openai.OpenAI(), model=model)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ragas.OpenAIEmbeddings: {type(exc).__name__}: {exc}")

    try:
        from langchain_openai import OpenAIEmbeddings as LangchainOpenAIEmbeddings
        from ragas.embeddings import LangchainEmbeddingsWrapper

        return LangchainEmbeddingsWrapper(
            LangchainOpenAIEmbeddings(model=model)
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"LangchainEmbeddingsWrapper: {type(exc).__name__}: {exc}")

    raise RuntimeError(
        "ragas 임베딩 래퍼를 만들지 못했습니다.\n  - " + "\n  - ".join(errors)
    )

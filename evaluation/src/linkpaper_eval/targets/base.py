"""평가 대상 시스템(SUT) 어댑터 인터페이스.

평가 하네스는 이 인터페이스만 알면 되므로, 백엔드 API를 호출하든 파이썬
파이프라인을 직접 임포트하든 동일한 지표로 비교할 수 있다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from linkpaper_eval.schemas import EvalCase, TargetResponse


class EvalTarget(ABC):
    """평가 대상 하나."""

    name: str = "target"

    @abstractmethod
    def run(self, case: EvalCase) -> TargetResponse:
        """케이스 하나를 실행한다. 예외는 던지지 말고 `error`에 담는다."""

    def close(self) -> None:
        """네트워크 연결 등 자원 정리."""


def build_target(spec: dict[str, Any]) -> EvalTarget:
    """설정 딕셔너리에서 타깃을 만든다.

    새 타깃을 추가할 때는 여기에 분기 하나만 더하면 된다.
    """
    target_type = spec.get("type", "lexical_baseline")
    options = spec.get("options", {}) or {}

    if target_type in {"lexical_baseline", "mock"}:
        from linkpaper_eval.targets.lexical_baseline import LexicalBaselineTarget

        return LexicalBaselineTarget(**options)

    if target_type in {"http", "http_backend", "backend"}:
        from linkpaper_eval.targets.http_backend import HttpBackendTarget

        return HttpBackendTarget(**options)

    raise ValueError(f"Unknown target type: {target_type}")

"""평가 설정.

설정 파일은 실행의 재현 단위다. 설정 해시를 실행 매니페스트에 기록해서
"어떤 조건으로 잰 점수인지"를 나중에도 확인할 수 있게 한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


class GateRule(BaseModel):
    """게이트 한 줄. 절대 기준과 회귀 허용치를 함께 지정할 수 있다."""

    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    max_regression: float | None = None


class RunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = 4
    output_dir: str = "runs"
    limit: int | None = None
    repeat: int = 1


class EvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite: str
    dataset: str
    target: dict[str, Any] = Field(default_factory=dict)
    targets: dict[str, dict[str, Any]] = Field(default_factory=dict)
    judge: dict[str, Any] = Field(default_factory=dict)
    k_values: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    gates: dict[str, GateRule] = Field(default_factory=dict)
    run: RunOptions = Field(default_factory=RunOptions)
    baseline: str | None = None

    # 설정 파일 위치. 상대 경로 해석 기준으로 쓴다.
    base_dir: Path = Field(default_factory=Path.cwd, exclude=True)

    def resolve(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    def sha256(self) -> str:
        payload = self.model_dump(mode="json", exclude={"base_dir"})
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _expand_env(value: Any) -> Any:
    """`${VAR:-default}` 형태를 환경변수로 치환한다."""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> EvalConfig:
    config_path = Path(path).resolve()
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    raw = _expand_env(raw)
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                raw[key] = value

    # 설정 파일 기준 디렉터리는 evaluation/ 루트(설정 파일의 부모의 부모가
    # 아니라 부모 디렉터리의 상위)로 잡아, configs/ 안에서 ../datasets 같은
    # 표기 없이 evaluation 루트 기준 경로를 쓸 수 있게 한다.
    raw["base_dir"] = config_path.parent.parent
    return EvalConfig.model_validate(raw)

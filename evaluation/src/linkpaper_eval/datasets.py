"""평가 데이터셋 로딩.

JSONL 한 줄이 케이스 하나다. 데이터셋 파일 해시를 실행 매니페스트에
기록하므로, 점수 변화가 시스템 변경 때문인지 데이터 변경 때문인지
구분할 수 있다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from linkpaper_eval.schemas import EvalCase


def load_cases(path: str | Path, limit: int | None = None) -> list[EvalCase]:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    cases: list[EvalCase] = []
    with dataset_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{dataset_path}:{line_number} is not valid JSON: {exc}"
                ) from exc
            cases.append(EvalCase.model_validate(payload))

    if not cases:
        raise ValueError(f"Dataset has no cases: {dataset_path}")

    duplicates = _find_duplicates([case.case_id for case in cases])
    if duplicates:
        raise ValueError(f"Duplicate case_id in {dataset_path}: {duplicates}")

    if limit is not None:
        cases = cases[:limit]
    return cases


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)

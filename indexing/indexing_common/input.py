"""전처리 파이프라인이 출력한 JSON을 builder 입력으로 읽는다."""

from __future__ import annotations

import json
from pathlib import Path

from data_pipeline.models import ProcessedPaper


def load_processed_papers(path: str | Path) -> list[ProcessedPaper]:
    """단일 논문 객체와 paper/daily/base 배열 JSON을 모두 지원한다."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    items = payload if isinstance(payload, list) else [payload]
    return [ProcessedPaper.model_validate(item) for item in items]

"""생성 결과를 `EvalCase` JSONL로 내보낸다.

ragas가 돌려주는 것은 질문·정답·근거 **텍스트**다. 반면 평가 지표는 근거를
**청크 ID**로 비교한다. 이 간극을 메우는 것이 이 모듈이다.

`reference_context_ids`와 본문이 일치하는지 검증하고, ID가 없으면 공백을
정규화한 본문이 유일하게 일치해야 한다. 근거가 일부라도 빠진 케이스는
전체를 제외하고 개수를 보고한다. 불완전한 정답으로 Recall을 왜곡하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.schemas import EvalCase
from linkpaper_eval.stores.records import ChunkRecord


class ExportReport(BaseModel):
    total: int = 0
    exported: int = 0
    dropped_no_gold: int = 0
    dropped_incomplete_evidence: int = 0
    dropped_missing_reference: int = 0
    dropped_duplicate: int = 0
    contexts_total: int = 0
    contexts_matched: int = 0
    tags: dict[str, int] = Field(default_factory=dict)

    @property
    def match_rate(self) -> float:
        if self.contexts_total == 0:
            return 1.0
        return self.contexts_matched / self.contexts_total

    def summary(self) -> str:
        return (
            f"생성 {self.total}건 중 {self.exported}건 내보냄 "
            f"(근거 매칭률 {self.match_rate:.1%}, "
            f"정답 청크 없어 제외 {self.dropped_no_gold}건, "
            f"근거 불완전 {self.dropped_incomplete_evidence}건, "
            f"정답 누락 {self.dropped_missing_reference}건, 중복 {self.dropped_duplicate}건)"
        )


def _case_id(question: str, index: int, prefix: str) -> str:
    digest = hashlib.sha1(question.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{index:04d}-{digest}"


def _rows_from_testset(testset: Any) -> list[dict[str, Any]]:
    """ragas Testset을 dict 목록으로 바꾼다.

    버전에 따라 `to_list`가 있기도 하고 없기도 해서 pandas 경로를
    대비책으로 둔다.
    """
    if hasattr(testset, "to_list"):
        try:
            return [dict(row) for row in testset.to_list()]
        except Exception:  # noqa: BLE001 - pandas 경로로 넘어간다
            pass
    frame = testset.to_pandas()
    return frame.to_dict(orient="records")


def testset_to_cases(
    testset: Any,
    chunks: list[ChunkRecord],
    prefix: str = "ragas",
) -> tuple[list[dict[str, Any]], ExportReport]:
    """ragas Testset → `EvalCase` 딕셔너리 목록."""
    report = ExportReport()
    lookup = {chunk.chunk_id: chunk for chunk in chunks}
    # Synthetic evidence must identify an actual source, not just similar text.
    by_text: dict[str, list[str]] = {}
    for chunk in chunks:
        by_text.setdefault(" ".join(chunk.text.split()), []).append(chunk.chunk_id)
    cases: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    for index, row in enumerate(_rows_from_testset(testset)):
        report.total += 1
        question = str(row.get("user_input") or row.get("question") or "").strip()
        if not question:
            continue
        reference = str(row.get("reference") or "").strip()
        if not reference:
            report.dropped_missing_reference += 1
            continue

        contexts = row.get("reference_contexts") or row.get("contexts") or []
        if isinstance(contexts, str):
            contexts = [contexts]

        supplied_ids = row.get("reference_context_ids") or []
        if supplied_ids and len(supplied_ids) != len(contexts):
            report.dropped_incomplete_evidence += 1
            continue
        gold_chunk_ids: list[str] = []
        matched_count = 0
        for position, context in enumerate(contexts):
            report.contexts_total += 1
            normalized = " ".join(str(context).split())
            candidates = by_text.get(normalized, [])
            if supplied_ids:
                proposed = str(supplied_ids[position])
                matched = proposed if proposed in candidates else None
            else:
                matched = candidates[0] if len(candidates) == 1 else None
            if matched:
                report.contexts_matched += 1
                matched_count += 1
                if matched not in gold_chunk_ids:
                    gold_chunk_ids.append(matched)

        if not gold_chunk_ids:
            report.dropped_no_gold += 1
            continue
        if matched_count != len(contexts):
            report.dropped_incomplete_evidence += 1
            continue
        identity = (" ".join(question.lower().split()), tuple(sorted(gold_chunk_ids)))
        if identity in seen:
            report.dropped_duplicate += 1
            continue
        seen.add(identity)

        gold_paper_ids = sorted(
            {
                lookup[chunk_id].paper_id
                for chunk_id in gold_chunk_ids
                if chunk_id in lookup
            }
        )
        synthesizer = str(row.get("synthesizer_name") or "").lower()
        multi_hop = "multi" in synthesizer or len(gold_chunk_ids) > 1

        tags = ["generated", "ragas"]
        tags.append("multi-hop" if multi_hop else "single-hop")
        tags.append("global" if len(gold_paper_ids) > 1 else "local")
        if synthesizer:
            tags.append(f"synthesizer:{synthesizer}")
        for tag in tags:
            report.tags[tag] = report.tags.get(tag, 0) + 1

        case: dict[str, Any] = {
            "case_id": _case_id(question, index, prefix),
            "question": question,
            "paper_id": gold_paper_ids[0] if gold_paper_ids else None,
            "gold_chunk_ids": gold_chunk_ids,
            "gold_paper_ids": gold_paper_ids,
            "grades": {chunk_id: 3 for chunk_id in gold_chunk_ids},
            "expected_scope": "global" if len(gold_paper_ids) > 1 else "selected",
            "tags": tags,
            "gold_answer": reference,
            "reference_contexts": [lookup[cid].text for cid in gold_chunk_ids],
            "source_metadata": [lookup[cid].model_dump(exclude={"text"}) for cid in gold_chunk_ids],
        }

        cases.append(case)
        report.exported += 1

    return cases, report


def validate_cases(
    cases: list[dict[str, Any]], chunks: list[ChunkRecord]
) -> list[str]:
    """스키마와 정답 ID 존재 여부를 확인한다.

    정답 ID에 오타가 있으면 Recall이 조용히 0이 된다. 기존 데이터셋에
    대해 테스트가 하던 검증을, 생성 경로에서도 내보내기 전에 한다.
    """
    known = {chunk.chunk_id for chunk in chunks}
    problems: list[str] = []
    seen: set[str] = set()

    for case in cases:
        try:
            parsed = EvalCase.model_validate(case)
        except Exception as exc:  # noqa: BLE001 - 문제를 모아서 보고한다
            problems.append(f"{case.get('case_id', '?')}: 스키마 위반 {exc}")
            continue
        if parsed.case_id in seen:
            problems.append(f"{parsed.case_id}: case_id 중복")
        seen.add(parsed.case_id)
        for chunk_id in parsed.gold_chunk_ids:
            if chunk_id not in known:
                problems.append(f"{parsed.case_id}: 코퍼스에 없는 청크 {chunk_id}")
        if not parsed.question.strip():
            problems.append(f"{parsed.case_id}: 빈 질문")
        if not parsed.gold_chunk_ids:
            problems.append(f"{parsed.case_id}: 정답 청크 없음")
    return problems


def write_cases(cases: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    return path

"""외부 벤치마크를 LinkPaper 평가 형식으로 변환한다.

변환 결과는 두 가지다.

- `corpus.jsonl` — `fixtures/mock_corpus.jsonl`과 같은 형식의 청크 코퍼스.
  기존 BM25 베이스라인 타깃이 그대로 읽고, Qdrant·Neo4j 적재의 입력도 된다.
- `<suite>.jsonl` — `schemas.EvalCase` 형식의 평가 케이스.

정답 근거를 청크 ID로 옮기는 과정이 이 모듈의 핵심이자 가장 깨지기 쉬운
부분이다. 원본 벤치마크는 근거를 "문단 텍스트"나 "문장"으로 주는데, 평가
지표는 청크 ID를 비교하기 때문이다. 매칭에 실패한 근거를 조용히 버리면
Recall이 이유 없이 낮게 나오므로, 실패율을 `ConversionReport`에 담아
prepare 명령이 항상 출력하게 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from linkpaper_eval.benchmark.download import read_jsonl, write_jsonl
from linkpaper_eval.metrics.generation import tokenize
from linkpaper_eval.stores.records import ChunkRecord

_WHITESPACE = re.compile(r"\s+")
# QASPER는 그림·표 근거를 이 접두사로 표시한다. 본문 문단이 아니므로
# 청크로 매칭할 수 없다.
_FLOAT_EVIDENCE = re.compile(r"^FLOAT SELECTED", re.IGNORECASE)

MIN_CHUNK_CHARS = 40


class ConversionReport(BaseModel):
    """변환 결과 요약. `manifest.json`에 그대로 저장한다."""

    benchmark: str
    chunk_count: int = 0
    paper_count: int = 0
    case_counts: dict[str, int] = Field(default_factory=dict)
    evidence_total: int = 0
    evidence_matched: int = 0
    skipped_cases: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def match_rate(self) -> float:
        if self.evidence_total == 0:
            return 1.0
        return self.evidence_matched / self.evidence_total

    def summary(self) -> str:
        cases = ", ".join(
            f"{suite}={count}" for suite, count in sorted(self.case_counts.items())
        )
        return (
            f"{self.benchmark}: 청크 {self.chunk_count}개 / 논문 "
            f"{self.paper_count}편 / 케이스 {cases or '없음'} / "
            f"근거 매칭률 {self.match_rate:.1%}"
        )


def normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", (text or "").strip()).lower()


def split_text(
    text: str, max_chars: int = 1200, overlap: int = 0
) -> list[str]:
    """문단 경계를 지키면서 긴 본문을 자른다.

    벤치마크 코퍼스는 기본 overlap을 0으로 둔다. 청크가 겹치면 같은 근거
    문장이 여러 청크에 들어가서 정답 청크가 하나로 정해지지 않고, Recall
    분모가 흔들린다. 서비스 인덱싱(overlap 150)과 다른 선택이며, 목적이
    다르기 때문이다.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    chunks: list[str] = []
    buffer = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            for start in range(0, len(paragraph), max_chars - overlap or max_chars):
                piece = paragraph[start : start + max_chars]
                if piece.strip():
                    chunks.append(piece.strip())
            continue

        if not buffer:
            buffer = paragraph
        elif len(buffer) + len(paragraph) + 2 <= max_chars:
            buffer = f"{buffer}\n\n{paragraph}"
        else:
            chunks.append(buffer)
            buffer = paragraph

    if buffer:
        chunks.append(buffer)
    return [chunk for chunk in chunks if len(chunk) >= MIN_CHUNK_CHARS]


class EvidenceMatcher:
    """근거 텍스트를 청크 ID로 옮긴다.

    엄격한 것부터 느슨한 것 순으로 시도한다. 느슨한 매칭을 먼저 하면
    엉뚱한 청크가 정답이 되어 지표가 조용히 왜곡된다.
    """

    def __init__(self, chunks: list[ChunkRecord], jaccard_threshold: float = 0.75):
        self.chunks = chunks
        self.jaccard_threshold = jaccard_threshold
        self._by_text: dict[str, str] = {}
        self._by_paper: dict[str, list[tuple[str, str, set[str]]]] = {}

        for chunk in chunks:
            normalized = normalize(chunk.text)
            self._by_text.setdefault(normalized, chunk.chunk_id)
            self._by_paper.setdefault(chunk.paper_id, []).append(
                (chunk.chunk_id, normalized, set(tokenize(chunk.text)))
            )

    def match(self, evidence: str, paper_id: str | None = None) -> str | None:
        normalized = normalize(evidence)
        if not normalized or _FLOAT_EVIDENCE.match(evidence.strip()):
            return None

        exact = self._by_text.get(normalized)
        if exact is not None:
            return exact

        candidates = (
            self._by_paper.get(paper_id, [])
            if paper_id
            else [item for items in self._by_paper.values() for item in items]
        )
        if not candidates:
            return None

        for chunk_id, chunk_text, _ in candidates:
            if normalized in chunk_text:
                return chunk_id
        for chunk_id, chunk_text, _ in candidates:
            if chunk_text and chunk_text in normalized:
                return chunk_id

        evidence_tokens = set(tokenize(evidence))
        if not evidence_tokens:
            return None
        best_id: str | None = None
        best_score = 0.0
        for chunk_id, _, chunk_tokens in candidates:
            if not chunk_tokens:
                continue
            overlap = len(evidence_tokens & chunk_tokens)
            score = overlap / len(evidence_tokens)
            if score > best_score:
                best_score, best_id = score, chunk_id
        return best_id if best_score >= self.jaccard_threshold else None


def _write_outputs(
    out_dir: Path,
    chunks: list[ChunkRecord],
    cases_by_suite: dict[str, list[dict[str, Any]]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "corpus.jsonl", (c.to_corpus_row() for c in chunks))
    for suite, cases in cases_by_suite.items():
        write_jsonl(out_dir / f"{suite}.jsonl", cases)


# ----------------------------------------------------------------------
# QASPER
# ----------------------------------------------------------------------


def convert_qasper(
    raw: dict[str, Path], out_dir: Path, limit: int | None = None
) -> ConversionReport:
    """QASPER를 논문 청크 코퍼스와 평가 케이스로 변환한다.

    문단 하나가 청크 하나다. 원본의 근거(evidence)가 문단 텍스트 그대로라
    이렇게 자르면 정답 매칭이 정확해진다. 서비스 청킹 규칙과는 다르지만,
    벤치마크의 정답 라벨을 훼손하지 않는 쪽을 택했다.
    """
    report = ConversionReport(benchmark="qasper")
    rows = read_jsonl(raw["qasper"])

    chunks: list[ChunkRecord] = []
    paper_questions: list[dict[str, Any]] = []

    for row in rows:
        paper_id = f"arxiv:{row.get('id', '')}".strip()
        if paper_id == "arxiv:":
            continue
        title = row.get("title") or ""

        units: list[tuple[str, str]] = []
        abstract = (row.get("abstract") or "").strip()
        if len(abstract) >= MIN_CHUNK_CHARS:
            units.append(("Abstract", abstract))

        full_text = row.get("full_text") or {}
        section_names = full_text.get("section_name") or []
        paragraph_groups = full_text.get("paragraphs") or []
        for index, paragraphs in enumerate(paragraph_groups):
            section = ""
            if index < len(section_names) and section_names[index]:
                section = str(section_names[index])
            for paragraph in paragraphs or []:
                text = (paragraph or "").strip()
                if len(text) >= MIN_CHUNK_CHARS:
                    units.append((section or "Body", text))

        if not units:
            continue

        paper_chunks = [
            ChunkRecord.build(
                paper_id=paper_id,
                chunk_index=index,
                text=text,
                section=section,
                title=title,
            )
            for index, (section, text) in enumerate(units)
        ]
        chunks.extend(paper_chunks)

        qas = row.get("qas") or {}
        questions = qas.get("question") or []
        question_ids = qas.get("question_id") or []
        answers = qas.get("answers") or []
        for index, question in enumerate(questions):
            paper_questions.append(
                {
                    "paper_id": paper_id,
                    "question": question,
                    "question_id": (
                        question_ids[index] if index < len(question_ids) else ""
                    ),
                    "answers": answers[index] if index < len(answers) else {},
                }
            )

    report.chunk_count = len(chunks)
    report.paper_count = len({chunk.paper_id for chunk in chunks})
    matcher = EvidenceMatcher(chunks)

    retrieval_cases: list[dict[str, Any]] = []
    generation_cases: list[dict[str, Any]] = []

    for item in paper_questions:
        if limit is not None and len(retrieval_cases) >= limit:
            break

        gold_chunk_ids: list[str] = []
        gold_answers: list[str] = []
        unanswerable = False

        for annotation in (item["answers"] or {}).get("answer", []) or []:
            if not isinstance(annotation, dict):
                continue
            if annotation.get("unanswerable"):
                unanswerable = True
            for evidence in annotation.get("evidence") or []:
                report.evidence_total += 1
                matched = matcher.match(evidence, item["paper_id"])
                if matched:
                    report.evidence_matched += 1
                    if matched not in gold_chunk_ids:
                        gold_chunk_ids.append(matched)

            free_form = (annotation.get("free_form_answer") or "").strip()
            spans = [s for s in (annotation.get("extractive_spans") or []) if s]
            if free_form:
                gold_answers.append(free_form)
            elif spans:
                gold_answers.append("; ".join(spans))

        if not gold_chunk_ids and not gold_answers:
            report.skipped_cases += 1
            continue

        case_id = f"qasper-{item['question_id'] or len(retrieval_cases)}"[:64]
        tags = ["qasper", "local"]
        if unanswerable:
            tags.append("unanswerable")

        base = {
            "case_id": case_id,
            "question": item["question"],
            "paper_id": item["paper_id"],
            "gold_chunk_ids": gold_chunk_ids,
            "gold_paper_ids": [item["paper_id"]],
            "expected_scope": "selected",
            "tags": tags,
        }
        if gold_chunk_ids:
            retrieval_cases.append(base)
        if gold_answers:
            generation_cases.append({**base, "gold_answer": gold_answers[0]})

    report.case_counts = {
        "retrieval": len(retrieval_cases),
        "generation": len(generation_cases),
    }
    if report.match_rate < 0.8:
        report.warnings.append(
            f"근거 매칭률이 {report.match_rate:.1%}로 낮습니다. 짧은 문단이 "
            "코퍼스에서 제외됐거나 원본 형식이 바뀌었을 수 있습니다."
        )

    _write_outputs(
        out_dir,
        chunks,
        {"retrieval": retrieval_cases, "generation": generation_cases},
    )
    return report


# ----------------------------------------------------------------------
# MultiHop-RAG
# ----------------------------------------------------------------------


def convert_multihop_rag(
    raw: dict[str, Path], out_dir: Path, limit: int | None = None
) -> ConversionReport:
    """MultiHop-RAG의 뉴스 코퍼스와 멀티홉 질의를 변환한다."""
    report = ConversionReport(benchmark="multihop-rag")

    corpus_rows = read_jsonl(raw["corpus"])
    chunks: list[ChunkRecord] = []
    doc_index: dict[str, str] = {}  # url/title 정규화 → paper_id

    for index, row in enumerate(corpus_rows):
        body = (row.get("body") or "").strip()
        if not body:
            continue
        paper_id = f"hf:multihoprag-{index:04d}"
        title = (row.get("title") or "").strip()
        for key in (row.get("url"), title):
            if key:
                doc_index[normalize(str(key))] = paper_id

        for chunk_index, text in enumerate(split_text(body)):
            chunks.append(
                ChunkRecord.build(
                    paper_id=paper_id,
                    chunk_index=chunk_index,
                    text=text,
                    section=row.get("category") or "Body",
                    title=title,
                )
            )

    report.chunk_count = len(chunks)
    report.paper_count = len({chunk.paper_id for chunk in chunks})
    matcher = EvidenceMatcher(chunks)

    retrieval_cases: list[dict[str, Any]] = []
    generation_cases: list[dict[str, Any]] = []

    for index, row in enumerate(read_jsonl(raw["queries"])):
        if limit is not None and index >= limit:
            break
        question = (row.get("query") or "").strip()
        if not question:
            continue

        question_type = str(row.get("question_type") or "unknown")
        gold_chunk_ids: list[str] = []
        gold_paper_ids: list[str] = []

        for evidence in row.get("evidence_list") or []:
            if not isinstance(evidence, dict):
                continue
            fact = (evidence.get("fact") or "").strip()
            if not fact:
                continue
            report.evidence_total += 1
            paper_id = doc_index.get(
                normalize(str(evidence.get("url") or ""))
            ) or doc_index.get(normalize(str(evidence.get("title") or "")))
            matched = matcher.match(fact, paper_id)
            if matched:
                report.evidence_matched += 1
                if matched not in gold_chunk_ids:
                    gold_chunk_ids.append(matched)
            if paper_id and paper_id not in gold_paper_ids:
                gold_paper_ids.append(paper_id)

        tags = ["multihop-rag", question_type]
        # 근거가 여러 문서에 걸쳐 있으면 확장이 필요한 질문이다.
        is_global = len(gold_paper_ids) > 1
        tags.append("global" if is_global else "local")
        if question_type == "null_query":
            tags.append("unanswerable")

        base = {
            "case_id": f"mhrag-{index:05d}",
            "question": question,
            "paper_id": gold_paper_ids[0] if gold_paper_ids else None,
            "gold_chunk_ids": gold_chunk_ids,
            "gold_paper_ids": gold_paper_ids,
            "expected_scope": "global" if is_global else "selected",
            "tags": tags,
        }
        if gold_chunk_ids:
            retrieval_cases.append(base)
        answer = (row.get("answer") or "").strip()
        if answer:
            generation_cases.append({**base, "gold_answer": answer})

    report.case_counts = {
        "retrieval": len(retrieval_cases),
        "generation": len(generation_cases),
    }
    _write_outputs(
        out_dir,
        chunks,
        {"retrieval": retrieval_cases, "generation": generation_cases},
    )
    return report


# ----------------------------------------------------------------------
# GraphRAG-Bench
# ----------------------------------------------------------------------


def convert_graphrag_bench(
    raw: dict[str, Path], out_dir: Path, limit: int | None = None
) -> ConversionReport:
    """GraphRAG-Bench 질문을 변환한다.

    코퍼스 파일을 확보하지 못하면 검색 스위트는 만들 수 없다. 그 경우
    생성 스위트만 내보내고 경고를 남긴다. 정답 청크 없이 검색 지표를
    만들어 내면 0점이 실력처럼 보이기 때문이다.
    """
    report = ConversionReport(benchmark="graphrag-bench")

    chunks: list[ChunkRecord] = []
    corpus_path = raw.get("corpus")
    if corpus_path and corpus_path.exists():
        for index, row in enumerate(read_jsonl(corpus_path)):
            body = (
                row.get("context")
                or row.get("text")
                or row.get("content")
                or row.get("corpus")
                or ""
            )
            body = str(body).strip()
            if not body:
                continue
            paper_id = f"hf:graphragbench-{index:04d}"
            title = str(row.get("title") or row.get("source") or "")
            for chunk_index, text in enumerate(split_text(body)):
                chunks.append(
                    ChunkRecord.build(
                        paper_id=paper_id,
                        chunk_index=chunk_index,
                        text=text,
                        section="Body",
                        title=title,
                    )
                )
    else:
        report.warnings.append(
            "코퍼스 파일이 없어 생성 스위트만 만듭니다. 검색 지표가 필요하면 "
            "데이터셋 Files 탭에서 코퍼스를 받아 raw/corpus.jsonl 로 두고 "
            "다시 실행하세요."
        )

    report.chunk_count = len(chunks)
    report.paper_count = len({chunk.paper_id for chunk in chunks})
    matcher = EvidenceMatcher(chunks) if chunks else None

    retrieval_cases: list[dict[str, Any]] = []
    generation_cases: list[dict[str, Any]] = []

    for index, row in enumerate(read_jsonl(raw["questions"])):
        if limit is not None and index >= limit:
            break
        question = str(row.get("question") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if not question:
            continue

        question_type = str(row.get("question_type") or "unknown")
        gold_chunk_ids: list[str] = []
        evidence = row.get("evidence")
        evidence_items = (
            evidence if isinstance(evidence, list) else [evidence] if evidence else []
        )
        for item in evidence_items:
            text = str(item or "").strip()
            if not text:
                continue
            report.evidence_total += 1
            matched = matcher.match(text) if matcher else None
            if matched:
                report.evidence_matched += 1
                if matched not in gold_chunk_ids:
                    gold_chunk_ids.append(matched)

        base = {
            "case_id": f"grbench-{row.get('id', index)}",
            "question": question,
            "gold_chunk_ids": gold_chunk_ids,
            "expected_scope": "global",
            "tags": ["graphrag-bench", question_type, "global"],
        }
        if gold_chunk_ids:
            retrieval_cases.append(base)
        if answer:
            generation_cases.append({**base, "gold_answer": answer})

    report.case_counts = {
        "retrieval": len(retrieval_cases),
        "generation": len(generation_cases),
    }
    outputs: dict[str, list[dict[str, Any]]] = {"generation": generation_cases}
    if retrieval_cases:
        outputs["retrieval"] = retrieval_cases
    _write_outputs(out_dir, chunks, outputs)
    return report


# ----------------------------------------------------------------------
# 로컬 픽스처
# ----------------------------------------------------------------------


def convert_local(
    raw: dict[str, Path], out_dir: Path, limit: int | None = None
) -> ConversionReport:
    """저장소 픽스처를 벤치마크 디렉터리 구조로 복사한다.

    다운로드가 없으므로 `prepare`가 저장소 안의 픽스처 경로를 `raw`에
    채워서 넘긴다. 다른 변환기와 입력 방식이 같으므로, 이 변환기만 출력
    디렉터리 위치로 저장소 루트를 되짚을 필요가 없다.
    """
    report = ConversionReport(benchmark="linkpaper-local")

    corpus_path = raw.get("corpus")
    if corpus_path is None or not corpus_path.exists():
        raise FileNotFoundError(
            f"픽스처 코퍼스를 찾을 수 없습니다: {corpus_path or 'raw[\'corpus\']'}"
        )

    chunks = [
        ChunkRecord(
            chunk_id=row["chunk_id"],
            paper_id=row.get("paper_id", ""),
            text=row.get("text", ""),
            section=row.get("section"),
        )
        for row in read_jsonl(corpus_path)
    ]
    report.chunk_count = len(chunks)
    report.paper_count = len({chunk.paper_id for chunk in chunks})

    cases_by_suite: dict[str, list[dict[str, Any]]] = {}
    for suite in ("retrieval", "generation", "extraction"):
        source = raw.get(suite)
        if source is None or not source.exists():
            continue
        rows = read_jsonl(source)
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            tags = list(row.get("tags") or [])
            if "linkpaper-local" not in tags:
                tags.append("linkpaper-local")
            row["tags"] = tags
        cases_by_suite[suite] = rows
        report.case_counts[suite] = len(rows)

    _write_outputs(out_dir, chunks, cases_by_suite)
    return report


CONVERTERS = {
    "qasper": convert_qasper,
    "multihop_rag": convert_multihop_rag,
    "graphrag_bench": convert_graphrag_bench,
    "local": convert_local,
}


def write_manifest(out_dir: Path, report: ConversionReport, extra: dict) -> Path:
    path = out_dir / "manifest.json"
    payload = {**report.model_dump(), "match_rate": report.match_rate, **extra}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path

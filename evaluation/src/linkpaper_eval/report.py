"""마크다운 리포트 생성.

PR에 그대로 붙일 수 있는 형태를 목표로 한다. 숫자 나열보다 "무엇이
나빠졌는가"가 먼저 보이도록 실패한 게이트와 최저 점수 케이스를 앞에 둔다.
"""

from __future__ import annotations

from pathlib import Path

from linkpaper_eval.gates import GateReport
from linkpaper_eval.schemas import RunResult

_HEADLINE = {
    "retrieval": [
        "retrieval.recall@5",
        "retrieval.ndcg@10",
        "retrieval.mrr",
        "routing.accuracy",
    ],
    "generation": [
        "generation.groundedness_lexical",
        "generation.citation_validity",
        "generation.citation_recall",
        "judge.faithfulness",
    ],
    "extraction": [
        "extraction.triple_f1",
        "extraction.relaxed_f1",
        "extraction.entity_coverage",
        "extraction.evidence_attachment",
    ],
}


def render(
    result: RunResult,
    gate_report: GateReport | None = None,
    baseline: dict[str, float] | None = None,
    worst_n: int = 5,
) -> str:
    manifest = result.manifest
    baseline = baseline or {}
    lines: list[str] = []

    lines.append(f"# 평가 리포트 — {manifest.suite}")
    lines.append("")
    lines.append(f"- 실행 ID: `{manifest.run_id}`")
    lines.append(f"- 대상: `{manifest.target}`")
    lines.append(f"- 데이터셋: `{manifest.dataset}` (sha `{manifest.dataset_sha256}`)")
    lines.append(f"- 설정 해시: `{manifest.config_sha256}`")
    if manifest.git_sha:
        lines.append(f"- 커밋: `{manifest.git_sha}`")
    if manifest.judge:
        lines.append(f"- 심판: `{manifest.judge}`")
    lines.append(f"- 케이스 수: {manifest.case_count}")
    lines.append("")

    if gate_report is not None:
        status = "✅ 통과" if gate_report.passed else "❌ 실패"
        lines.append(f"## 게이트 {status}")
        lines.append("")
        lines.append("| 지표 | 값 | 베이스라인 | 결과 | 사유 |")
        lines.append("|---|---:|---:|:---:|---|")
        for outcome in gate_report.outcomes:
            value = f"{outcome.value:.4f}" if outcome.value is not None else "—"
            reference = (
                f"{outcome.baseline:.4f}" if outcome.baseline is not None else "—"
            )
            mark = "✅" if outcome.passed else "❌"
            lines.append(
                f"| `{outcome.metric}` | {value} | {reference} | {mark} | "
                f"{outcome.reason} |"
            )
        lines.append("")

    headline = _HEADLINE.get(manifest.suite)
    if headline:
        available = [name for name in headline if name in result.aggregate]
        if available:
            lines.append("## 핵심 지표")
            lines.append("")
            lines.append(_metric_table(available, result.aggregate, baseline))
            lines.append("")

    lines.append("## 전체 지표")
    lines.append("")
    lines.append(_metric_table(sorted(result.aggregate), result.aggregate, baseline))
    lines.append("")

    if result.by_tag:
        lines.append("## 태그별 결과")
        lines.append("")
        tag_metrics = _tag_columns(manifest.suite, result)
        header = "| 태그 | 케이스 | " + " | ".join(f"`{m}`" for m in tag_metrics) + " |"
        lines.append(header)
        lines.append("|---|---:|" + "---:|" * len(tag_metrics))
        for tag, values in result.by_tag.items():
            count = int(values.get("operational.case_count", 0))
            cells = " | ".join(
                f"{values[metric]:.4f}" if metric in values else "—"
                for metric in tag_metrics
            )
            lines.append(f"| {tag} | {count} | {cells} |")
        lines.append("")

    failures = [case for case in result.cases if case.error]
    if failures:
        lines.append(f"## 실패 케이스 ({len(failures)}건)")
        lines.append("")
        for case in failures[:worst_n]:
            lines.append(f"- `{case.case_id}`: {case.error}")
        if len(failures) > worst_n:
            lines.append(f"- … 외 {len(failures) - worst_n}건")
        lines.append("")

    primary = _primary_metric(manifest.suite)
    scored = [
        case for case in result.cases if not case.error and primary in case.metrics
    ]
    if scored:
        scored.sort(key=lambda case: case.metrics[primary])
        lines.append(f"## 취약 케이스 (`{primary}` 하위 {worst_n}건)")
        lines.append("")
        lines.append("| case_id | 값 | 질문 | 기대 범위 | 실제 범위 |")
        lines.append("|---|---:|---|---|---|")
        for case in scored[:worst_n]:
            question = case.question[:60].replace("|", "\\|")
            lines.append(
                f"| `{case.case_id}` | {case.metrics[primary]:.4f} | {question} | "
                f"{case.expected_scope} | {case.actual_scope} |"
            )
        lines.append("")

    return "\n".join(lines)


def _metric_table(
    names: list[str],
    aggregate: dict[str, float],
    baseline: dict[str, float],
) -> str:
    rows = ["| 지표 | 값 | 베이스라인 | 변화 |", "|---|---:|---:|---:|"]
    for name in names:
        value = aggregate[name]
        reference = baseline.get(name)
        if reference is None:
            rows.append(f"| `{name}` | {value:.4f} | — | — |")
        else:
            delta = value - reference
            sign = "+" if delta >= 0 else ""
            rows.append(
                f"| `{name}` | {value:.4f} | {reference:.4f} | {sign}{delta:.4f} |"
            )
    return "\n".join(rows)


def _tag_columns(suite: str, result: RunResult) -> list[str]:
    candidates = _HEADLINE.get(suite, [])[:2]
    available = [
        metric
        for metric in candidates
        if any(metric in values for values in result.by_tag.values())
    ]
    return available or ["operational.latency_ms_p50"]


def _primary_metric(suite: str) -> str:
    return {
        "retrieval": "retrieval.recall@5",
        "generation": "generation.groundedness_lexical",
        "extraction": "extraction.triple_f1",
        "full": "retrieval.recall@5",
    }.get(suite, "retrieval.recall@5")


def write(text: str, path: str | Path) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return report_path

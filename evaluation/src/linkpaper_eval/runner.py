"""평가 실행 오케스트레이터.

케이스 실행 → 지표 계산 → 집계 → 산출물 저장까지의 흐름을 담당한다.
스위트마다 다른 것은 "어떤 지표를 계산하는가"뿐이므로 실행 골격은 공유한다.
"""

from __future__ import annotations

import json
import math
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from linkpaper_eval import metrics as metric_lib
from linkpaper_eval.config import EvalConfig
from linkpaper_eval.datasets import file_sha256, load_cases
from linkpaper_eval.judges import Judge, build_judge
from linkpaper_eval.metrics import extraction, generation, retrieval
from linkpaper_eval.schemas import (
    CaseResult,
    EvalCase,
    RunManifest,
    RunResult,
    TargetResponse,
)
from linkpaper_eval.targets import EvalTarget, build_target

SUITES = {"retrieval", "generation", "extraction", "full"}


def run_suite(config: EvalConfig, run_id: str | None = None) -> RunResult:
    if config.suite not in SUITES:
        raise ValueError(
            f"Unknown suite '{config.suite}'. Choose one of {sorted(SUITES)}."
        )

    dataset_path = config.resolve(config.dataset)
    cases = load_cases(dataset_path, limit=config.run.limit)

    target_spec = dict(config.target)
    options = dict(target_spec.get("options", {}) or {})
    if "corpus" in options:
        options["corpus"] = str(config.resolve(options["corpus"]))
    target_spec["options"] = options

    target = build_target(target_spec)
    judge = build_judge(config.judge) if config.suite in {"generation", "full"} else None

    started_at = datetime.now(timezone.utc)
    run_id = run_id or f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{config.suite}"

    results = _execute(cases, target, judge, config)

    finished_at = datetime.now(timezone.utc)
    target.close()

    manifest = RunManifest(
        run_id=run_id,
        suite=config.suite,
        target=target.name,
        dataset=str(dataset_path.relative_to(config.base_dir))
        if dataset_path.is_relative_to(config.base_dir)
        else str(dataset_path),
        dataset_sha256=file_sha256(dataset_path),
        config_sha256=config.sha256(),
        git_sha=_git_sha(),
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        case_count=len(results),
        judge=judge.name if judge else None,
    )

    return RunResult(
        manifest=manifest,
        aggregate=metric_lib.aggregate(results),
        by_tag=metric_lib.aggregate_by_tag(results),
        cases=results,
    )


def _execute(
    cases: list[EvalCase],
    target: EvalTarget,
    judge: Judge | None,
    config: EvalConfig,
) -> list[CaseResult]:
    def handle(case: EvalCase) -> CaseResult:
        try:
            response = target.run(case)
        except Exception as exc:  # noqa: BLE001 - 한 케이스 실패로 실행을 멈추지 않는다
            response = TargetResponse(error=f"{type(exc).__name__}: {exc}")
        return _score_case(case, response, judge, config)

    concurrency = max(1, config.run.concurrency)
    if concurrency == 1:
        return [handle(case) for case in cases]

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(handle, cases))


def _score_case(
    case: EvalCase,
    response: TargetResponse,
    judge: Judge | None,
    config: EvalConfig,
) -> CaseResult:
    ranked = response.ranked_chunk_ids()
    computed: dict[str, float] = {}

    if response.error is None:
        if config.suite in {"retrieval", "full"}:
            grades = {chunk_id: case.grade_of(chunk_id) for chunk_id in case.graded_ids()}
            computed.update(
                retrieval.evaluate_case(
                    ranked=ranked,
                    gold=case.graded_ids(),
                    grades=grades,
                    k_values=config.k_values,
                )
            )
            computed["retrieval.paper_hit@5"] = retrieval.hit_at_k(
                [item.paper_id or "" for item in response.retrieved],
                case.gold_paper_ids,
                5,
            )
            computed["routing.accuracy"] = retrieval.routing_correct(
                case.expected_scope, response.scope
            )

        if config.suite in {"generation", "full"}:
            computed.update(generation.evaluate_case(case, response))
            if judge is not None:
                computed.update(judge.score(case, response))

        if config.suite in {"extraction", "full"}:
            computed.update(extraction.evaluate_case(response.triples, case.gold_triples))

    return CaseResult(
        case_id=case.case_id,
        question=case.question,
        expected_scope=case.expected_scope,
        actual_scope=response.scope,
        metrics={
            key: value
            for key, value in computed.items()
            if not (isinstance(value, float) and math.isnan(value))
        },
        latency_ms=response.latency_ms,
        error=response.error,
        answer=response.answer,
        citations=response.citations,
        retrieved_chunk_ids=ranked[:10],
        tags=case.tags,
    )


def save_run(result: RunResult, output_dir: Path) -> Path:
    """실행 산출물을 `runs/<run_id>/`에 저장한다."""
    run_dir = output_dir / result.manifest.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "manifest.json").write_text(
        result.manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "metrics.json").write_text(
        json.dumps(
            {"aggregate": result.aggregate, "by_tag": result.by_tag},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with (run_dir / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in result.cases:
            handle.write(case.model_dump_json() + "\n")

    return run_dir


def _git_sha() -> str | None:
    try:
        output = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = output.stdout.strip()
    return sha or None

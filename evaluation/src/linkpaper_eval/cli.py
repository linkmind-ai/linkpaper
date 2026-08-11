"""평가 CLI.

    python -m linkpaper_eval run --config configs/retrieval.yaml
    python -m linkpaper_eval run --config configs/retrieval.yaml --target http
    python -m linkpaper_eval baseline --config configs/retrieval.yaml --run-id <id>
    python -m linkpaper_eval bench prepare --name qasper
    python -m linkpaper_eval testgen --source neo4j --engine ragas --size 50

의존성을 늘리지 않으려고 argparse만 사용한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from linkpaper_eval.config import load_config
from linkpaper_eval.gates import evaluate_gates, load_baseline, save_baseline
from linkpaper_eval.report import render, write
from linkpaper_eval.runner import save_run, run_suite
from linkpaper_eval.schemas import RunResult

_BUILTIN_TARGETS = {
    "baseline": {
        "type": "lexical_baseline",
        "options": {"corpus": "fixtures/mock_corpus.jsonl"},
    },
    "http": {
        "type": "http_backend",
        "options": {"base_url": "http://localhost:8000"},
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkpaper-eval",
        description="LinkPaper GraphRAG 평가 하네스",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="평가 스위트를 실행한다")
    run_parser.add_argument("--config", required=True, help="설정 YAML 경로")
    run_parser.add_argument("--suite", help="설정의 suite 값을 덮어쓴다")
    run_parser.add_argument("--dataset", help="설정의 dataset 경로를 덮어쓴다")
    run_parser.add_argument(
        "--target",
        help="설정의 targets 블록 또는 내장 프리셋(baseline | http) 이름",
    )
    run_parser.add_argument("--limit", type=int, help="앞에서 N개 케이스만 실행")
    run_parser.add_argument("--run-id", help="실행 ID를 직접 지정")
    run_parser.add_argument("--baseline", help="비교할 베이스라인 JSON 경로")
    run_parser.add_argument(
        "--no-gates",
        action="store_true",
        help="게이트를 평가하지 않고 리포트만 만든다",
    )
    run_parser.add_argument(
        "--quiet", action="store_true", help="리포트를 표준출력에 쓰지 않는다"
    )

    baseline_parser = subparsers.add_parser(
        "baseline", help="실행 결과를 베이스라인으로 저장한다"
    )
    baseline_parser.add_argument("--config", required=True)
    baseline_parser.add_argument("--run-id", required=True)
    baseline_parser.add_argument("--output", help="베이스라인 저장 경로")

    show_parser = subparsers.add_parser("show", help="저장된 실행 결과를 출력한다")
    show_parser.add_argument("--config", required=True)
    show_parser.add_argument("--run-id", required=True)

    # 벤치마크와 평가셋 생성 명령은 별도 패키지에서 등록한다. 위 세 명령의
    # 동작에는 영향이 없고, 등록이 실패해도 기존 명령은 그대로 쓸 수 있다.
    try:
        from linkpaper_eval.benchmark.cli import register as register_extras

        register_extras(subparsers)
    except Exception as exc:  # noqa: BLE001 - 부가 명령이 핵심 경로를 막지 않는다
        print(f"부가 명령을 등록하지 못했습니다: {exc}", file=sys.stderr)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 부가 명령은 서브파서가 handler를 직접 지정한다.
    handler = getattr(args, "handler", None)
    if handler is not None:
        return handler(args)

    if args.command == "run":
        return _command_run(args)
    if args.command == "baseline":
        return _command_baseline(args)
    if args.command == "show":
        return _command_show(args)
    return 1


def _command_run(args: argparse.Namespace) -> int:
    overrides: dict[str, object] = {}
    if args.suite:
        overrides["suite"] = args.suite
    if args.dataset:
        overrides["dataset"] = args.dataset
    if args.baseline:
        overrides["baseline"] = args.baseline

    config = load_config(args.config, overrides)

    if args.target:
        # 타깃을 바꿀 때는 옵션까지 통째로 교체한다. 옵션은 타깃 종류마다
        # 다르므로 병합하면 이전 타깃의 옵션이 딸려간다.
        spec = config.targets.get(args.target) or _BUILTIN_TARGETS.get(args.target)
        if spec is None:
            available = sorted({*config.targets, *_BUILTIN_TARGETS})
            print(
                f"알 수 없는 타깃: {args.target} (사용 가능: {', '.join(available)})",
                file=sys.stderr,
            )
            return 2
        config.target = dict(spec)
    if args.limit:
        config.run.limit = args.limit

    result = run_suite(config, run_id=args.run_id)
    output_dir = config.resolve(config.run.output_dir)
    run_dir = save_run(result, output_dir)

    baseline_values = load_baseline(
        config.resolve(config.baseline) if config.baseline else None
    )
    gate_report = None
    if not args.no_gates and config.gates:
        gate_report = evaluate_gates(result.aggregate, config.gates, baseline_values)

    report_text = render(result, gate_report, baseline_values)
    write(report_text, run_dir / "report.md")

    if not args.quiet:
        print(report_text)
    print(f"\n산출물: {run_dir}", file=sys.stderr)

    if gate_report is not None and not gate_report.passed:
        print("\n게이트 실패:", file=sys.stderr)
        for outcome in gate_report.failures():
            print(f"  - {outcome.metric}: {outcome.reason}", file=sys.stderr)
        return 1
    return 0


def _command_baseline(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    run_dir = config.resolve(config.run.output_dir) / args.run_id
    result = _load_run(run_dir)
    if result is None:
        print(f"실행 결과를 찾을 수 없습니다: {run_dir}", file=sys.stderr)
        return 2

    output = args.output or config.baseline or f"baselines/{config.suite}.json"
    path = save_baseline(result, config.resolve(output))
    print(f"베이스라인 저장: {path}")
    return 0


def _command_show(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    run_dir = config.resolve(config.run.output_dir) / args.run_id
    report_path = run_dir / "report.md"
    if report_path.exists():
        print(report_path.read_text(encoding="utf-8"))
        return 0
    print(f"리포트를 찾을 수 없습니다: {report_path}", file=sys.stderr)
    return 2


def _load_run(run_dir: Path) -> RunResult | None:
    manifest_path = run_dir / "manifest.json"
    metrics_path = run_dir / "metrics.json"
    if not manifest_path.exists() or not metrics_path.exists():
        return None

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    cases = []
    cases_path = run_dir / "cases.jsonl"
    if cases_path.exists():
        with cases_path.open(encoding="utf-8") as handle:
            cases = [json.loads(line) for line in handle if line.strip()]

    return RunResult.model_validate(
        {
            "manifest": manifest,
            "aggregate": metrics.get("aggregate", {}),
            "by_tag": metrics.get("by_tag", {}),
            "cases": cases,
        }
    )

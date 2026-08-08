"""Data Pipeline 실행 진입점.

    python -m data_pipeline paper 2406.04093
    python -m data_pipeline daily --date 2026-08-08
    python -m data_pipeline base --month 2026-08 --limit 10

주기 실행은 이 모듈이 담당하지 않는다. 스케줄러나 Job이 위 명령 또는
`DataPipeline`의 `run_base_corpus` / `run_daily_papers`를 호출한다.

결과는 표준출력으로만 내보낸다. 중간 산출물을 파일로 남기는 기능은 두지
않는다. 정규화 결과의 저장은 Graph Builder 쪽 책임이다.

의존성을 늘리지 않으려고 argparse만 사용한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime

from data_pipeline.config import configure_logging
from data_pipeline.models import PipelineRun, ProcessedPaper
from data_pipeline.pipeline import DataPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkpaper-data-pipeline",
        description="Hugging Face Papers 수집·전처리 파이프라인",
    )
    parser.add_argument("--log-level", help="로그 레벨 (기본값은 설정값)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="처리 결과 전체를 JSON으로 표준출력에 쓴다",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_parser = subparsers.add_parser("paper", help="논문 한 편을 처리한다")
    paper_parser.add_argument("paper_id", help="Hugging Face Papers ID (예: 2406.04093)")

    daily_parser = subparsers.add_parser(
        "daily", help="특정 날짜의 Daily Papers를 처리한다"
    )
    daily_parser.add_argument("--date", help="YYYY-MM-DD (기본값: 오늘)")
    daily_parser.add_argument("--limit", type=int, help="앞에서 N편만 처리")

    base_parser = subparsers.add_parser(
        "base", help="베이스 코퍼스(해당 월 전체)를 처리한다"
    )
    base_parser.add_argument("--month", help="YYYY-MM (기본값: 이번 달)")
    base_parser.add_argument("--limit", type=int, help="앞에서 N편만 처리")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)

    try:
        with DataPipeline() as pipeline:
            if args.command == "paper":
                return _command_paper(pipeline, args)
            if args.command == "daily":
                return _command_daily(pipeline, args)
            if args.command == "base":
                return _command_base(pipeline, args)
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    return 1


def _command_paper(pipeline: DataPipeline, args: argparse.Namespace) -> int:
    try:
        paper = pipeline.process_paper_id(args.paper_id)
    except Exception as exc:
        print(f"처리 실패 {args.paper_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_paper_summary(paper)
    if args.json:
        print(_dumps(paper.model_dump(mode="json")))
    return 0


def _command_daily(pipeline: DataPipeline, args: argparse.Namespace) -> int:
    day = _parse_date(args.date) if args.date else None
    run = pipeline.run_daily_papers(day, limit=args.limit)
    return _report(run, args.json)


def _command_base(pipeline: DataPipeline, args: argparse.Namespace) -> int:
    year, month = _parse_month(args.month) if args.month else (None, None)
    run = pipeline.run_base_corpus(year, month, limit=args.limit)
    return _report(run, args.json)


def _report(run: PipelineRun, as_json: bool) -> int:
    papers = run.papers
    failures = run.failures
    print(
        f"[{run.mode}] {run.window} 처리 {len(run.outcomes)}편 "
        f"(성공 {len(papers)} / 실패 {len(failures)}), "
        f"청크 {sum(len(paper.chunks) for paper in papers)}개",
        file=sys.stderr,
    )
    for failure in failures:
        print(
            f"  실패 {failure.paper_id} [{failure.stage}] {failure.error}",
            file=sys.stderr,
        )

    if as_json:
        print(_dumps([paper.model_dump(mode="json") for paper in papers]))
    else:
        for paper in papers:
            _print_paper_summary(paper)

    # 전부 실패했을 때만 실패로 본다. 일부 실패는 배치의 정상 결과다.
    return 1 if papers == [] and failures else 0


def _print_paper_summary(paper: ProcessedPaper) -> None:
    metadata = paper.metadata
    sections = {chunk.section for chunk in paper.chunks}
    print(
        f"{metadata.paper_id} | {metadata.title[:60]} | "
        f"source={metadata.source_version} sections={len(sections)} "
        f"chunks={len(paper.chunks)} references={len(metadata.references)}",
        file=sys.stderr,
    )


def _dumps(payload: object) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"날짜 형식은 YYYY-MM-DD입니다: {value}") from exc


def _parse_month(value: str) -> tuple[int, int]:
    try:
        parsed = datetime.strptime(value, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"월 형식은 YYYY-MM입니다: {value}") from exc
    return parsed.year, parsed.month

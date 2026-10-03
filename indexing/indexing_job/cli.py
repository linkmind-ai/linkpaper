"""오프라인 인덱싱 통합 CLI."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime, timedelta

from data_pipeline.config import configure_logging
from indexing_job.job import IndexingJob, IndexingRun


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkpaper-indexing",
        description="Hugging Face 논문 전처리 후 Neo4j와 Qdrant에 적재",
    )
    parser.add_argument("--log-level", default=None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_parser = subparsers.add_parser("paper", help="논문 한 편을 적재한다")
    paper_parser.add_argument("paper_id")
    paper_parser.add_argument("--global-corpus", action="store_true")

    daily_parser = subparsers.add_parser("daily", help="특정 날짜 논문을 적재한다")
    daily_window = daily_parser.add_mutually_exclusive_group()
    daily_window.add_argument("--date", help="YYYY-MM-DD (기본값: 오늘)")
    daily_window.add_argument(
        "--days-ago",
        type=int,
        help="UTC 기준 N일 전 날짜를 적재한다 (cron용, 1 = 어제)",
    )
    daily_parser.add_argument("--limit", type=int)
    daily_parser.add_argument("--global-corpus", action="store_true")

    base_parser = subparsers.add_parser("base", help="해당 월 전체를 적재한다")
    base_parser.add_argument("--month", help="YYYY-MM (기본값: 이번 달)")
    base_parser.add_argument("--limit", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        with IndexingJob() as job:
            if args.command == "paper":
                run = job.paper(args.paper_id, in_global_corpus=args.global_corpus)
            elif args.command == "daily":
                run = job.daily(
                    _resolve_day(args.date, args.days_ago),
                    limit=args.limit,
                    in_global_corpus=args.global_corpus,
                )
            else:
                year, month = _parse_month(args.month) if args.month else (None, None)
                run = job.base(year, month, limit=args.limit)
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 최상위 오류 경계
        print(f"인덱싱 실행 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    _print_summary(run)
    return 1 if run.failures else 0


def _print_summary(run: IndexingRun) -> None:
    print(
        f"[{run.mode}] {run.window} 인덱싱 "
        f"성공 {len(run.successes)} / 실패 {len(run.failures)} "
        f"global={run.in_global_corpus}",
        file=sys.stderr,
    )
    for failure in run.failures:
        print(
            f"  실패 {failure.paper_id} [{failure.stage}] {failure.error}",
            file=sys.stderr,
        )


def _resolve_day(value: str | None, days_ago: int | None) -> date | None:
    if value:
        return _parse_date(value)
    if days_ago is None:
        return None
    if days_ago < 0:
        raise ValueError(f"--days-ago는 0 이상이어야 합니다: {days_ago}")
    # HF Daily Papers의 날짜 경계가 UTC라 실행 호스트의 시간대와 무관하게 계산한다.
    return datetime.now(UTC).date() - timedelta(days=days_ago)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"날짜 형식은 YYYY-MM-DD입니다: {value}") from exc


def _parse_month(value: str) -> tuple[int, int]:
    try:
        parsed = date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValueError(f"월 형식은 YYYY-MM입니다: {value}") from exc
    return parsed.year, parsed.month

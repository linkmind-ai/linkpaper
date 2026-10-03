from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from indexing_job.cli import _resolve_day, build_parser


def test_days_ago_resolves_from_utc_today() -> None:
    assert _resolve_day(None, 1) == datetime.now(UTC).date() - timedelta(days=1)


def test_explicit_date_is_used_as_is() -> None:
    assert _resolve_day("2026-08-08", None) == date(2026, 8, 8)


def test_no_window_keeps_pipeline_default() -> None:
    assert _resolve_day(None, None) is None


def test_negative_days_ago_is_rejected() -> None:
    with pytest.raises(ValueError):
        _resolve_day(None, -1)


def test_date_and_days_ago_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["daily", "--date", "2026-08-08", "--days-ago", "1"])

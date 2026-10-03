#!/usr/bin/env bash
# 전날(UTC) Daily Papers를 글로벌 코퍼스(base DB)에 반영한다. cron에서 호출한다.
#
#   0 10 * * * /path/to/linkpaper/scripts/index_daily_papers.sh
#
# 인자를 주면 `daily` 기본 인자를 대체한다. 누락된 날짜를 채울 때 쓴다.
#
#   scripts/index_daily_papers.sh --date 2026-10-01
set -uo pipefail

# cron의 기본 PATH에는 docker가 없다.
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

cd "$(dirname "$0")/.."
mkdir -p logs
log_file="logs/index_daily_papers.log"

if [ "$#" -eq 0 ]; then
    set -- --days-ago 1
fi

echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily $* 시작" >> "$log_file"
# cron에는 TTY가 없으므로 -T로 실행한다.
docker compose run --rm -T indexing daily "$@" --global-corpus >> "$log_file" 2>&1
status=$?
echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily $* 종료 exit=$status" >> "$log_file"
exit "$status"

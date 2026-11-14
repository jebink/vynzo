#!/usr/bin/env bash
# Cron wrapper: load .env, run one worker job, log to logs/<package>_<job>_<date>.log.
#   infra/cron/run_job.sh <python-package> <job> [job args...]
#   e.g.  market_ingestion eod
#         analytics_worker high-volume-buy --days 3
# - Never runs the same <package> <job> twice at once (flock on logs/.<package>_<job>.lock);
#   a busy lock logs a line and exits 0.
# - Deletes logs/*.log older than 30 days.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PKG="${1:?usage: run_job.sh <package> <job> [args...]}"
JOB="${2:?usage: run_job.sh <package> <job> [args...]}"
shift 2
# shellcheck disable=SC1091
[[ -f .env ]] && { set -a; source .env; set +a; }
mkdir -p logs
LOG="logs/${PKG}_${JOB}_$(date -u +%Y%m%d).log"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# cron's PATH is minimal; the uv installer puts uv in ~/.local/bin.
UV="$(command -v uv || true)"
[[ -z "$UV" && -x "$HOME/.local/bin/uv" ]] && UV="$HOME/.local/bin/uv"
if [[ -z "$UV" ]]; then
  echo "$(ts) error $PKG $JOB: uv not found on PATH or in \$HOME/.local/bin" >>"$LOG"
  exit 127
fi

if command -v flock >/dev/null; then
  exec 9>"logs/.${PKG}_${JOB}.lock"
  if ! flock -n 9; then
    echo "$(ts) skip $PKG $JOB: previous run still holds the lock" >>"$LOG"
    exit 0
  fi
else
  echo "$(ts) warn $PKG $JOB: flock not found, running without the overlap lock" >>"$LOG"
fi

find logs -maxdepth 1 -name '*.log' -type f -mtime +30 -delete

echo "$(ts) start $PKG $JOB $*" >>"$LOG"
"$UV" run --frozen python -m "$PKG" "$JOB" "$@" >>"$LOG" 2>&1
echo "$(ts) done $PKG $JOB" >>"$LOG"

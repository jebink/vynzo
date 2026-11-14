#!/usr/bin/env bash
# Deploy VYNZO locally or to the dev server.
#
#   scripts/deploy.sh local [start|stop|status]     # production build on this machine
#   scripts/deploy.sh dev [--ref <git-ref>] [--skip-checks] [--yes] [--dry-run]
#
# local: installs dependencies, builds the web app and runs the API (:8000) and web (:3000) in
#   the background (pids in .run/, logs in logs/). Uses the database in .env (DATABASE_URL).
#   Migrations run only against a local database: when .env reaches the dev server through
#   scripts/tunnel.sh, dev's migrations belong to `deploy.sh dev`.
#
# dev: ships one git commit (default HEAD; committed files only) to $DEV_DIR on $DEV_SSH, then
#   on the server: installs dependencies from the lockfiles, backs up the database and migrates
#   if a migration is pending, builds the web app, installs the systemd units from
#   infra/systemd if they changed, restarts vynzo-api and vynzo-web, and health-checks both.
#   It reports, but never rewrites, a crontab that differs from infra/cron/crontab.
#   SSH asks for the server password once (none with an SSH key); sudo asks for it on restart.
#   --dry-run connects and shows what would be shipped and deleted, and changes nothing.
#
# Settings (environment or .env): DEV_SSH (admin@192.168.31.11), DEV_DIR (/home/admin/vynzo),
# DEV_API_URL (http://<dev host>:8000, baked into the web build), API_PORT (8000), WEB_PORT (3000).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# One value from .env, verbatim (no shell parsing: CORS_ORIGINS holds JSON). The environment
# wins over .env. The services read .env themselves, so it is never exported wholesale.
env_get() {
  local value="${!1:-}"
  [[ -z "$value" && -f .env ]] && value="$(grep -E "^$1=" .env | tail -1 | cut -d= -f2-)"
  printf '%s' "${value:-${2:-}}"
}
DEV_SSH="$(env_get DEV_SSH admin@192.168.31.11)"
DEV_DIR="$(env_get DEV_DIR /home/admin/vynzo)"
DEV_HOST="${DEV_SSH#*@}"
DEV_API_URL="$(env_get DEV_API_URL "http://$DEV_HOST:8000")"
API_PORT="$(env_get API_PORT 8000)"
WEB_PORT="$(env_get WEB_PORT 3000)"
RUN_DIR="$ROOT/.run"
UNITS=(vynzo-api vynzo-web)

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Wait up to ~60s for a URL to answer 2xx/3xx.
wait_http() {
  local url=$1
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null --max-time 5 "$url" 2>/dev/null && { echo "  ok  $url"; return 0; }
    sleep 1
  done
  echo "  FAIL $url" >&2
  return 1
}

# ---------------------------------------------------------------- local

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

local_stop() {
  local name pid
  for name in web api; do
    [[ -f "$RUN_DIR/$name.pid" ]] || continue
    pid="$(cat "$RUN_DIR/$name.pid")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -9 "$pid" 2>/dev/null || true
      echo "stopped $name (pid $pid)"
    fi
    rm -f "$RUN_DIR/$name.pid"
  done
}

local_status() {
  local name pid up=0
  for name in api web; do
    pid="$(cat "$RUN_DIR/$name.pid" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$name: running (pid $pid)"; up=1
    else
      echo "$name: stopped"
    fi
  done
  [[ $up -eq 1 ]]
}

local_start() {
  [[ -f .env ]] || die "no .env (copy .env.example and fill it in)"
  local database_url api_url
  database_url="$(env_get DATABASE_URL)"
  [[ -n "$database_url" ]] || die "set DATABASE_URL in .env"
  api_url="$(env_get NEXT_PUBLIC_API_BASE_URL "http://localhost:$API_PORT")"

  say "Dependencies"
  uv sync --all-packages --frozen
  pnpm install --frozen-lockfile

  say "Database"
  local hostport db_host db_port
  hostport="$(sed -E 's#^[^@]*@([^/?]+).*#\1#' <<<"$database_url")"
  db_host="${hostport%:*}"; db_port="${hostport##*:}"
  [[ "$db_port" == "$hostport" ]] && db_port=5432
  if ! (exec 3<>"/dev/tcp/$db_host/$db_port") 2>/dev/null; then
    die "nothing answers at $db_host:$db_port. Start the dev tunnel (scripts/tunnel.sh) or a local database (make db-up)."
  fi
  if scripts/tunnel.sh status >/dev/null 2>&1 && [[ "$db_port" == "$(env_get TUNNEL_LOCAL_PORT 5432)" ]]; then
    echo "$db_host:$db_port is the dev server (tunnel): skipping migrations; 'deploy.sh dev' applies them."
  else
    scripts/migrate.sh up
  fi

  say "Build web (API at $api_url)"
  NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_BASE_URL="$api_url" pnpm --filter @vynzo/web build

  say "Start"
  local_stop
  local port
  for port in "$API_PORT" "$WEB_PORT"; do
    if port_busy "$port"; then
      lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2
      die "port $port is in use by another process (a 'make api'/'make web' dev server?). Stop it first."
    fi
  done
  mkdir -p "$RUN_DIR" logs
  # Background only the server itself, so the pid file names it and it holds no pipe of ours.
  cd "$ROOT/services/api"
  nohup uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" --workers 2 \
    </dev/null >>"$ROOT/logs/api.log" 2>&1 &
  echo $! >"$RUN_DIR/api.pid"
  cd "$ROOT/apps/web"
  nohup node_modules/.bin/next start --hostname 127.0.0.1 --port "$WEB_PORT" \
    </dev/null >>"$ROOT/logs/web.log" 2>&1 &
  echo $! >"$RUN_DIR/web.pid"
  cd "$ROOT"

  say "Health"
  wait_http "http://localhost:$API_PORT/health" && wait_http "http://localhost:$WEB_PORT/dashboard" \
    || die "not healthy; see logs/api.log and logs/web.log"
  echo
  echo "Local deploy up: web http://localhost:$WEB_PORT  api http://localhost:$API_PORT"
  echo "Stop with: scripts/deploy.sh local stop"
}

# ---------------------------------------------------------------- dev

SOCK="/tmp/vynzo-deploy-$$.sock"
remote() { ssh -S "$SOCK" "$DEV_SSH" "$@"; }

dev_deploy() {
  local ref=HEAD checks=1 assume_yes=0 dry_run=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --ref) ref="${2:?--ref needs a git ref}"; shift 2 ;;
      --skip-checks) checks=0; shift ;;
      --yes|-y) assume_yes=1; shift ;;
      --dry-run|-n) dry_run=1; checks=0; assume_yes=1; shift ;;
      *) die "unknown option: $1" ;;
    esac
  done

  local sha subject
  sha="$(git rev-parse --short "$ref^{commit}")" || die "unknown ref: $ref"
  subject="$(git log -1 --format=%s "$sha")"
  if [[ "$ref" == HEAD ]] && ! { git diff --quiet && git diff --cached --quiet; }; then
    die "uncommitted changes: commit them (only committed files are deployed) or pass --ref"
  fi

  if [[ $checks -eq 1 ]]; then
    say "Checks (skip with --skip-checks)"
    uv run pytest services -q
    pnpm -r typecheck
  fi

  echo
  echo "Deploy $sha \"$subject\" to $DEV_SSH:$DEV_DIR"
  if [[ $assume_yes -eq 0 ]]; then
    read -r -p "Continue? [y/N] " answer
    [[ "$answer" == [yY]* ]] || die "cancelled"
  fi

  say "Connect"
  ssh -o ControlPersist=15m -M -S "$SOCK" -fN "$DEV_SSH"
  trap 'ssh -S "$SOCK" -O exit "$DEV_SSH" >/dev/null 2>&1 || true; rm -rf "${STAGE:-}"' EXIT

  say "Ship $sha"
  STAGE="$(mktemp -d)"
  git archive "$sha" | tar -x -C "$STAGE"
  echo "$sha" >"$STAGE/REVISION"
  # Server-only files: never sent (not in the archive) and protected from --delete.
  local protect=(
    --filter='P /.env' --filter='P /.env.*' --filter='P /logs/' --filter='P /data/'
    --filter='P /.venv/' --filter='P node_modules/' --filter='P /apps/web/.next/'
    --filter='P __pycache__/' --filter='P .pytest_cache/' --filter='P .ruff_cache/'
    --filter='P *.tsbuildinfo' --filter='P next-env.d.ts'
  )
  local changes deletions
  changes="$(rsync -azc --delete --dry-run --itemize-changes "${protect[@]}" -e "ssh -S $SOCK" \
    "$STAGE/" "$DEV_SSH:$DEV_DIR/")"
  deletions="$(grep -c '^\*deleting' <<<"$changes" || true)"
  echo "$(grep -c '^<f' <<<"$changes" || true) files to send, $deletions to delete"
  grep '^\*deleting' <<<"$changes" | head -20 || true
  if [[ $dry_run -eq 1 ]]; then
    echo
    echo "Dry run: nothing was changed on $DEV_SSH. Server now runs $(remote cat "$DEV_DIR/REVISION" 2>/dev/null || echo unknown)."
    remote "cd $DEV_DIR && PATH=\$HOME/.local/bin:\$PATH scripts/migrate.sh status" | grep -E '^\[ \]|Pending' || true
    return 0
  fi
  rsync -azc --delete "${protect[@]}" -e "ssh -S $SOCK" "$STAGE/" "$DEV_SSH:$DEV_DIR/"

  say "Install, migrate, build (on the server)"
  remote bash -s -- "$DEV_DIR" "$DEV_API_URL" <<'REMOTE'
set -euo pipefail
cd "$1"; export PATH="$HOME/.local/bin:$PATH"
uv sync --all-packages --frozen
pnpm install --frozen-lockfile
pending="$(scripts/migrate.sh status | grep -c '^\[ \]' || true)"
if [[ "$pending" -gt 0 ]]; then
  echo "$pending pending migration(s): backing up first"
  scripts/backup_db.sh
  scripts/migrate.sh up
else
  echo "no pending migrations"
fi
NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_BASE_URL="$2" pnpm --filter @vynzo/web build
REMOTE

  say "Restart services (sudo may ask for the server password)"
  local unit changed=()
  for unit in "${UNITS[@]}"; do
    remote "cmp -s $DEV_DIR/infra/systemd/$unit.service /etc/systemd/system/$unit.service" \
      || changed+=("$unit")
  done
  local cmd="sudo systemctl restart ${UNITS[*]}"
  if [[ ${#changed[@]} -gt 0 ]]; then
    echo "unit files changed: ${changed[*]}"
    local installs=""
    for unit in "${changed[@]}"; do
      installs+="sudo install -m 644 $DEV_DIR/infra/systemd/$unit.service /etc/systemd/system/ && "
    done
    cmd="${installs}sudo systemctl daemon-reload && $cmd"
  fi
  ssh -t -S "$SOCK" "$DEV_SSH" "$cmd"

  say "Health"
  wait_http "http://$DEV_HOST:8000/health" && wait_http "http://$DEV_HOST:3000/dashboard" \
    || die "not healthy; on the server: journalctl -u vynzo-api -u vynzo-web -n 100"

  say "Cron"
  if remote bash -s -- "$DEV_DIR" <<'CRON'; then
diff <(crontab -l | grep -v '^#' | grep .) <(grep -v '^#' "$1/infra/cron/crontab" | grep .)
CRON
    echo "crontab matches infra/cron/crontab"
  else
    echo "WARNING: the server crontab differs from infra/cron/crontab (diff above)."
    echo "Update it by hand (docs/runbooks/identity-migration.md, step 'Install the new jobs')."
  fi

  echo
  echo "Deployed $sha to dev: web http://$DEV_HOST:3000  api http://$DEV_HOST:8000"
}

# ---------------------------------------------------------------- main

case "${1:-}" in
  local)
    case "${2:-start}" in
      start) local_start ;;
      stop) local_stop ;;
      status) local_status ;;
      *) die "usage: scripts/deploy.sh local [start|stop|status]" ;;
    esac ;;
  dev) shift; dev_deploy "$@" ;;
  *) echo "usage: scripts/deploy.sh local [start|stop|status] | dev [--ref <ref>] [--skip-checks] [--yes] [--dry-run]" >&2
     exit 2 ;;
esac

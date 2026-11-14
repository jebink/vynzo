#!/usr/bin/env bash
# Run dbmate (in Docker) against DATABASE_URL using database/postgres/migrations.
#   scripts/migrate.sh            # = up
#   scripts/migrate.sh status|up|rollback|new <name>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -z "${DATABASE_URL:-}" && -f "$ROOT/.env" ]] && { set -a; source "$ROOT/.env"; set +a; }
: "${DATABASE_URL:?set DATABASE_URL in .env (see .env.example)}"

DBMATE_IMAGE="${DBMATE_IMAGE:-ghcr.io/amacneil/dbmate:2}"
URL="$DATABASE_URL"
NET=(--network host)
if [[ "$(uname)" == "Darwin" ]]; then
  # Docker Desktop: the host is reachable as host.docker.internal, not localhost.
  URL="${URL/@localhost/@host.docker.internal}"
  URL="${URL/@127.0.0.1/@host.docker.internal}"
  NET=()
fi

[[ $# -eq 0 ]] && set -- up
exec docker run --rm ${NET[@]+"${NET[@]}"} \
  -u "$(id -u):$(id -g)" \
  -v "$ROOT/database/postgres:/db" \
  -e DATABASE_URL="$URL" \
  "$DBMATE_IMAGE" --migrations-dir /db/migrations --no-dump-schema "$@"

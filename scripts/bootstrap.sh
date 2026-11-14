#!/usr/bin/env bash
# First-time local setup: env file, Python and JS dependencies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f .env ]] || { cp .env.example .env; echo "created .env: fill in DATABASE_URL"; }
[[ -f infra/compose/timescaledb/.env ]] || {
  cp infra/compose/timescaledb/.env.example infra/compose/timescaledb/.env
  echo "created infra/compose/timescaledb/.env: set POSTGRES_PASSWORD"
}
command -v uv >/dev/null || { echo "install uv: brew install uv" >&2; exit 1; }
command -v pnpm >/dev/null || { echo "install pnpm: corepack enable" >&2; exit 1; }
uv sync --all-packages
pnpm install
echo "done. next: make db-up && make migrate"

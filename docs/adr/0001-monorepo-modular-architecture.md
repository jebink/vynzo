# 1. Monorepo with a modular API and a few workers

Date: 2026-11-11 · Status: accepted

## Context

VYNZO will cover market-data ingestion, fundamentals, analytics, grading, screening, portfolios,
a website and a mobile app, on a self-hosted budget under ₹10,000/month.

## Decision

- One monorepo (`apps/`, `services/`, `packages/`, `database/`, `infra/`).
- Python for the API and all Phase 1 workers (uv workspace). Market ingestion stays in Python while
  data is EOD batch. Revisit Go when licensed tick feeds arrive (Phase 3).
- Next.js for `apps/web`, pnpm workspaces for JS.
- PostgreSQL + TimescaleDB, migrations in `database/postgres` via dbmate.
- vinzo-core was replaced by a clean rewrite. Its code is archived outside the repo
  (`vinzo-core-backup-2026-11-11.tar.gz`) as the reference for porting.

## Consequences

Few deployable processes and one lockfile per language. A service is split out only for an
operational reason (architecture rule 7).

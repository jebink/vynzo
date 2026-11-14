# VYNZO

Stock market research and intelligence platform for NSE/BSE equities.

Monorepo: Python services (uv workspace), Next.js web (pnpm workspace), PostgreSQL + TimescaleDB.
See [docs/architecture.md](docs/architecture.md) for the target architecture, phases and rules.
**Phase 1 is in progress**; later-phase folders contain only a README.

| Path | Contents |
|---|---|
| `apps/web` | Next.js website |
| `services/api` | FastAPI, one module per business domain |
| `services/market-ingestion` | EOD market-data ingestion (NSE/BSE/vendor adapters) |
| `services/fundamentals-worker` | Financial statements, corporate actions |
| `services/analytics-worker` | Indicators, signals, news sentiment |
| `database/postgres` | Migrations (dbmate): the only place schema changes |
| `infra/compose`, `infra/cron` | TimescaleDB stack, scheduled jobs |
| `scripts/` | bootstrap, migrate, backup/restore |
| `docs/` | Architecture, ADRs, runbooks |

## Setup

Requires: Python 3.13, [uv](https://docs.astral.sh/uv/), Node 24, pnpm 9, Docker.

```bash
scripts/bootstrap.sh   # creates .env files, installs dependencies
make db-up             # TimescaleDB on :5432
make migrate           # apply database/postgres/migrations
make api               # http://localhost:8000/docs
make web               # http://localhost:3000
```

`make help` lists every target. Secrets live only in git-ignored `.env` files.

## Status

Skeleton only. Worker jobs raise `NotImplementedError` and API modules have no endpoints yet.
Features are being ported from the archived vinzo-core code (`vinzo-core-backup-2026-11-11.tar.gz`,
kept outside the repo).
# vynzo

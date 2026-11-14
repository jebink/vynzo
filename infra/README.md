# infra

| Folder | Contents |
|---|---|
| `compose/timescaledb/` | TimescaleDB (PostgreSQL 16) for local dev and the self-hosted server |
| `cron/` | Scheduled jobs: crontab and job wrapper |

The Compose project name stays `timescaledb` so the existing data volume
(`timescaledb_timescaledb_data`) still attaches after the move.

# infra

| Folder | Contents |
|---|---|
| `compose/timescaledb/` | TimescaleDB (PostgreSQL 16) for local dev and the self-hosted server |
| `systemd/` | API and web units for the dev server (scheduled jobs live in `vynzo_batch/cron/`) |

The Compose project name stays `timescaledb` so the existing data volume
(`timescaledb_timescaledb_data`) still attaches after the move.

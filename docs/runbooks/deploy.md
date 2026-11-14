# Deploy

`scripts/deploy.sh` deploys the app on this machine or on the dev server (192.168.31.11).
Settings come from the environment or `.env` (see `.env.example`).

## Local

```bash
scripts/deploy.sh local          # make deploy-local: install, build, run API :8000 + web :3000
scripts/deploy.sh local status
scripts/deploy.sh local stop     # make deploy-local-stop
```

Production mode (`next build` + `next start`, uvicorn with 2 workers) in the background; pids in
`.run/`, logs in `logs/api.log` and `logs/web.log`. For hot reload use `make api` / `make web`
instead (stop the local deploy first: both use ports 8000 and 3000).

The database is whatever `DATABASE_URL` in `.env` points at. With `scripts/tunnel.sh` up it is
the dev server, and migrations are skipped (they belong to the dev deploy); against a local
database (`make db-up`) migrations run.

## Dev server

```bash
scripts/deploy.sh dev --dry-run  # what would ship and be deleted; changes nothing
scripts/deploy.sh dev            # make deploy-dev: deploy HEAD (must be committed)
scripts/deploy.sh dev --ref <commit|branch|tag>
```

Steps: unit tests and typecheck (`--skip-checks` skips) → confirm → ship the commit with
`git archive` + rsync to `/home/admin/vynzo` (`REVISION` records it) → `uv sync` and
`pnpm install` from the lockfiles → if a migration is pending, `vynzo_batch/backup_db.sh` then
`scripts/migrate.sh up` → `next build` with `DEV_API_URL` → install `infra/systemd/*.service` if
changed → `sudo systemctl restart vynzo-api vynzo-web` → health checks on :8000 and :3000 → warns
if the crontab differs from `vynzo_batch/cron/crontab` (never rewrites it).

Only committed files ship. Server-only files are never sent or deleted: `.env*`, `logs/`, `data/`,
`.venv/`, `node_modules/`, `apps/web/.next/`.

SSH asks for the server password once and sudo once more at the restart. To skip the SSH
prompt: `ssh-copy-id admin@192.168.31.11`.

**Roll back:** `scripts/deploy.sh dev --ref <previous commit>` (the old commit is in
`/home/admin/vynzo/REVISION` before you deploy). A migration is not rolled back by this; use
`scripts/migrate.sh rollback` on the server, or restore the backup the deploy took
(`~/backups/vynzo`, see `backup-restore.md`).

If unhealthy: `journalctl -u vynzo-api -u vynzo-web -n 100` on the server.

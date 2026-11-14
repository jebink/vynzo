# Identity migration and ingestion cutover

Moves vinzo-core's legacy market data (symbol/exchange keyed) into the listing-keyed schema
(migrations `…06`–`…11`) and replaces the old cron with the VYNZO pipeline. Spec:
`docs/superpowers/specs/2026-11-11-identity-migration-and-ingestion-design.md` (section 8).

Placeholders: `$DEV_URL` is the dev DB URL (never printed or committed), `<stamp>` is a UTC
timestamp such as `20261111_101500`. Old server layout: code at `/home/admin/vinzo/vinzo-core`,
new code at `/home/admin/vynzo`.

## 1. Backup (dev DB)

```bash
mkdir -p data/raw/backups
docker exec timescaledb pg_dump "$DEV_URL" -Fc -Z 6 > data/raw/backups/dev_market_<stamp>.dump
ls -lh data/raw/backups/dev_market_<stamp>.dump         # expect > 50 MB
docker exec -i timescaledb pg_restore --list < data/raw/backups/dev_market_<stamp>.dump | head
```

## 2. Rehearsal on a local restore

Stop the local API (`make api`) so it releases its pool connections. Check local `market` is empty
first, since it is dropped and recreated. Every rehearsal command gets the local URL explicitly:

```bash
LOCAL_URL=$(grep ^DATABASE_URL= .env | cut -d= -f2-)    # never echo it
docker exec timescaledb psql -U market -d postgres -c 'DROP DATABASE market' -c 'CREATE DATABASE market'
docker exec timescaledb psql -U market -d market -c 'CREATE EXTENSION IF NOT EXISTS timescaledb'
docker exec timescaledb psql -U market -d market -c 'SELECT timescaledb_pre_restore()'
docker exec -i timescaledb pg_restore -U market -d market --no-owner < data/raw/backups/dev_market_<stamp>.dump
docker exec timescaledb psql -U market -d market -c 'SELECT timescaledb_post_restore()'
```

Verify row counts against the dev counts in the spec ("Current state"). Then:

```bash
DATABASE_URL="$LOCAL_URL" scripts/migrate.sh up          # 06-11; each copy migration has a count guard
DATABASE_URL="$LOCAL_URL" uv run python -m market_ingestion sync-reference
uv run python scripts/parity_check.py --db "$LOCAL_URL"  # exit 0 needs both gates >= 0.99
```

If a copy fails with `out of shared memory`, use the spec section 3 step 4 fallback. Below 99%
parity, stop and report. Then run the live chain against Yahoo (a handful of listings first, then
all):

```bash
DATABASE_URL="$LOCAL_URL" uv run python -m market_ingestion eod
DATABASE_URL="$LOCAL_URL" uv run python -m analytics_worker indicators
DATABASE_URL="$LOCAL_URL" uv run python -m analytics_worker high-volume-buy
DATABASE_URL="$LOCAL_URL" uv run python -m market_ingestion freshness
```

Expect all exit 0 and 278 rows in `ohlcv_latest`. Restart the API (`make api`) and check
`curl localhost:8000/health/ready` returns `{"status":"ok","db":"ok"}`.

### Parity gate

`parity_check.py` is read-only (autocommit, SELECTs only) and needs `legacy.*`, so it must run
before the drop. Options: `--sample 25 --window 60 --seed 7 --threshold 0.99`. The last stdout line
is JSON `{"ta_rate", "hvb_recall", "hvb_new_only", "hvb_legacy_only", "pass"}`.

- Pass needs TA match rate >= threshold AND HVB recall >= threshold.
- HVB recall = share of legacy HVB hits the new code reproduces over the same per-listing windows.
- New-only HVB hits are informational, not failures: legacy history came from one backfill on
  2026-11-09 (as_of 2026-09-25..11-06) over only the 152 listings ingested on 2026-11-08, plus a
  days=1 run on 11-11, so legacy never scanned every (listing, date).
- Within that scope new and legacy are identical (245 = 245).
- If legacy has 0 HVB hits, the script says the recall gate is vacuous.

## 3. Dev cutover

Every command below passes `DATABASE_URL="$DEV_URL"` (or `--db "$DEV_URL"`) explicitly.

1. **Stop the old cron, keeping a copy.** On the server, save the whole crontab, then remove the
   vinzo-core block right away (as of 2026-11-11 the admin crontab held only that block):
   ```bash
   mkdir -p ~/backups
   crontab -l > ~/backups/crontab_before_vynzo_<stamp>.txt
   grep -c 'vinzo-core' ~/backups/crontab_before_vynzo_<stamp>.txt       # expect >= 2 (the markers)
   crontab -l | sed '/^# >>> vinzo-core >>>$/,/^# <<< vinzo-core <<<$/d' | crontab -
   crontab -l | grep -c vinzo-core                                         # expect 0
   ```
   The old block includes the nightly backup, so **no nightly backup runs from here until the new
   crontab is installed in step 4**. Step 2 takes a fresh backup; don't let steps 1-4 stretch past
   a day.
2. **Back up again** (section 1) right before migrating.
3. **Migrate dev:**
   ```bash
   DATABASE_URL="$DEV_URL" scripts/migrate.sh up
   DATABASE_URL="$DEV_URL" uv run python -m market_ingestion sync-reference
   uv run python scripts/parity_check.py --db "$DEV_URL"
   ```
   Verify per-table row counts (legacy vs new) and 278 rows in `ohlcv_latest`. No API runs on dev,
   so there is no `/health/ready` to check.

   **If `parity_check.py` exits non-zero (TA match rate or HVB recall below the threshold), STOP.**
   Do not deploy. Roll back with section 4 (first bullet: `rollback` down to `…06`) and restore the
   old cron from the saved file, then report.
4. **Deploy the code** to `/home/admin/vynzo`. Run rsync from the repo root on the workstation,
   dry run first:
   ```bash
   EXCL=(--exclude .git --exclude .env --exclude .venv --exclude node_modules \
     --exclude data/raw --exclude logs --exclude __pycache__ --exclude .superpowers)
   rsync -az --delete --dry-run "${EXCL[@]}" ./ admin@192.168.31.11:/home/admin/vynzo/
   rsync -az --delete "${EXCL[@]}" ./ admin@192.168.31.11:/home/admin/vynzo/
   ```
   On the server, install uv and the environment. The repo-root `.python-version` pins Python 3.13
   (the server's system Python is 3.14), so `uv sync` downloads a managed 3.13 the first time:
   ```bash
   cd ~/vynzo
   command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
   export PATH="$HOME/.local/bin:$PATH"
   uv sync --all-packages --frozen
   uv run python --version              # expect 3.13.x
   uv run pytest services vynzo_batch -q            # one-time check on the server; expect all passed
   mkdir -p logs
   ```
   **Create `~/vynzo/.env`** from `.env.example` (mode 600). `DATABASE_URL` is the old
   `MARKET_DB_URL` with the host set to `127.0.0.1:5432` (the `timescaledb` container's host port);
   `KUMA_PUSH_URL` is copied if set. Nothing secret is echoed; the script prints only host, port,
   database name and whether Kuma is set:
   ```bash
   cd ~/vynzo
   ( umask 077; cp .env.example .env ); chmod 600 .env
   python3 - ~/vinzo/vinzo-core/.env .env <<'PY'
   import sys, urllib.parse as u
   old_path, new_path = sys.argv[1], sys.argv[2]
   old = {}
   for line in open(old_path):
       line = line.strip().removeprefix("export ")
       if "=" in line and not line.startswith("#"):
           k, v = line.split("=", 1)
           old[k.strip()] = v.strip().strip("'\"")
   p = u.urlsplit(old["MARKET_DB_URL"])
   userinfo = p.netloc.rsplit("@", 1)[0]
   db_url = u.urlunsplit(p._replace(netloc=f"{userinfo}@127.0.0.1:5432"))
   vals = {"DATABASE_URL": db_url, "KUMA_PUSH_URL": old.get("KUMA_PUSH_URL", "")}
   out = []
   for line in open(new_path):
       key = line.split("=", 1)[0]
       out.append(f"{key}={vals[key]}\n" if "=" in line and key in vals else line)
   open(new_path, "w").writelines(out)
   q = u.urlsplit(db_url)
   print("DATABASE_URL ->", q.hostname, q.port, q.path, "| KUMA_PUSH_URL set:", bool(vals["KUMA_PUSH_URL"]))
   PY
   ls -l .env                                  # expect -rw-------
   ```
   **`BACKUP_REMOTE`** stays empty (local backups only) until you set it by hand, with an editor, to
   a **new** remote directory, e.g. the same host as the old value but a `.../vynzo` subdirectory
   (create it on the remote first). **Never point it at the old vinzo-core backup directory:**
   `vynzo_batch/backup_db.sh` runs `rsync --delete --include='market_*.dump'`, which would delete the
   old off-host dumps that are not in `~/backups/vynzo`. Check without printing either value:
   ```bash
   new=$(grep '^BACKUP_REMOTE=' .env | cut -d= -f2-)
   old=$(grep '^BACKUP_REMOTE=' ~/vinzo/vinzo-core/.env | cut -d= -f2-)
   if [ -z "$new" ]; then echo "BACKUP_REMOTE empty: local backups only"
   elif [ "${new%/}" = "${old%/}" ]; then echo "STOP: same directory as the old vinzo-core remote"
   else echo "BACKUP_REMOTE is a different directory: ok"; fi
   unset new old
   ```
   The old local dumps stay in `~/backups/vinzo`; the new script writes to `~/backups/vynzo` and
   never prunes the old directory.

   **Smoke test** the wrapper and `.env`:
   ```bash
   vynzo_batch/cron/run_job.sh market_ingestion freshness; echo "exit=$?"
   tail -n 5 logs/market_ingestion_freshness_$(date -u +%Y%m%d).log
   ```
   The log must hold one JSON line (`{"fresh": ..., "latest": ..., ...}`) after the `start` line.
   `exit=1` with `"fresh": false` is fine at this point (the data is a day or so old, and the wrapper
   then skips its `done` line); a traceback or a connection error is not. With `KUMA_PUSH_URL` set,
   this also pushes the result to Uptime Kuma.

   **Install the new jobs by appending** `vynzo_batch/cron/crontab` to the (now vinzo-core-free) crontab.
   Never replace the crontab wholesale. Run it once; check first that it is not already there:
   ```bash
   crontab -l | grep -c VYNZO_ROOT          # expect 0 before installing
   (crontab -l; cat ~/vynzo/vynzo_batch/cron/crontab) | crontab -
   crontab -l | grep -c vinzo-core          # expect 0
   crontab -l | grep -c 'run_job.sh'        # expect 2 (the 17:00 chain and the 18:30 freshness)
   crontab -l                               # check; adjust VYNZO_ROOT/PATH in the file first if the paths differ
   ```
   The nightly backup is scheduled again from here.
5. **First live run by hand,** then let cron take over:
   ```bash
   vynzo_batch/cron/run_job.sh market_ingestion eod && vynzo_batch/cron/run_job.sh analytics_worker indicators \
     && vynzo_batch/cron/run_job.sh analytics_worker high-volume-buy --days 3 \
     && vynzo_batch/cron/run_job.sh market_ingestion freshness
   ```
   `run_job.sh` passes extra arguments through, takes a per-job `flock` (a second copy of the same
   job logs `skip` and exits 0), and deletes `logs/*.log` older than 30 days.
6. **Drop legacy (needs the user's explicit approval).** Show the user the verification report
   (row counts, parity). Only after a yes, with a fresh verified dump, move **all four** pending
   files (`…12`–`…15`) and apply them. Each is its own transaction; the largest peaked at 20.6k of
   the 31.2k dev lock table in rehearsal (see `database/postgres/pending/README.md`), so run it
   only after the pre-drop dump has finished and outside the 02:30 IST backup and the 17:00 IST
   job chain:
   ```bash
   git mv database/postgres/pending/2026111100001[2-5]_drop_legacy_*.sql database/postgres/migrations/
   ls database/postgres/pending/*.sql 2>/dev/null | wc -l      # expect 0
   DATABASE_URL="$DEV_URL" scripts/migrate.sh up
   DATABASE_URL="$DEV_URL" scripts/migrate.sh status           # 12-15 applied
   ```
   Then check `select to_regnamespace('legacy')` is NULL and the public row counts match the
   verification report. If one file fails (e.g. `out of shared memory`), the earlier ones stay
   applied and nothing is half-dropped: clear the cause and re-run `migrate.sh up`.

## 4. Rollback

- **Before the drop, right after migrating (nothing new written):**
  `DATABASE_URL="$DEV_URL" scripts/migrate.sh rollback` repeatedly, down to `...06`. This moves
  `legacy.*` back to `public`. Anything written after cutover is lost; the restored old cron
  re-fetches a few days of EOD bars.
- **After cutover (new pipeline has written data, before the drop):** roll back through `...07`,
  never `...11` alone. `...11` empties tables with `RESTART IDENTITY`, so new `ingest_run` ids could
  be reused while `raw_eod_bars` rows still reference them. Run rollback from 11 down through 07 in
  one go, then continue to 06 if the identity tables must go too.
- **Restore the old cron** in either case above: `crontab ~/backups/crontab_before_vynzo_<stamp>.txt`
  (the saved file, on the server).
- **After the drop:** restore from the section 1 dump with `pre_restore`/`post_restore`
  (see `docs/runbooks/backup-restore.md`).

## 5. Known issues

- **Duplicate weeks for three listings.** Legacy has Tuesday-dated weekly bars for APOLLOTYRE and
  TMPV (3,165 rows) and a Wednesday 2026-11-11 `1w`/`1mo` bar for BSE:INFY. The `eod` overlap
  re-fetches recent weeks Monday-dated from Yahoo, so these listings get a Monday bar and a Tuesday
  (or Wednesday) bar for the same week. Analytics reads only `1d`, so nothing downstream is
  affected. Cleaning up the off-day legacy rows is a later decision for the user.

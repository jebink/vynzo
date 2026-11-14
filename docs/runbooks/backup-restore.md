# Backup and restore

`vynzo_batch/backup_db.sh` runs nightly (see `vynzo_batch/cron/crontab`). It writes a compressed `pg_dump`
to `$BACKUP_DIR` (default `~/backups/vynzo`), keeps `$BACKUP_KEEP` days (default 14) and copies
to `$BACKUP_REMOTE` when set.

```bash
vynzo_batch/backup_db.sh                                              # on demand
scripts/restore_db.sh ~/backups/vynzo/market_<stamp>.dump         # restores into "market_restore"
scripts/restore_db.sh ~/backups/vynzo/market_<stamp>.dump market  # replace production (asks to confirm)
```

Restores use TimescaleDB's `timescaledb_pre_restore()` / `timescaledb_post_restore()`.
Stop scheduled jobs (`crontab -e`) before restoring over production.

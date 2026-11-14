#!/usr/bin/env bash
# Restore a backup made by vynzo_batch/backup_db.sh into a database (TimescaleDB-aware).
#
#   scripts/restore_db.sh <dump-file> [target-db]
#
# Default target is "market_restore" so production is never overwritten by accident.
# To replace production: stop jobs (crontab -e), then pass "market" explicitly.
set -euo pipefail
DUMP="${1:?usage: restore_db.sh <dump-file> [target-db]}"
TARGET="${2:-market_restore}"
CONTAINER="${DB_CONTAINER:-timescaledb}"
P=(docker exec -i "$CONTAINER" psql -U market -v ON_ERROR_STOP=1 -qAt)

if [[ "$TARGET" == "market" ]]; then
  read -r -p "This DROPS and replaces the production 'market' database. Type 'market' to continue: " ok
  [[ "$ok" == "market" ]] || { echo "aborted"; exit 1; }
fi

"${P[@]}" -d postgres -c "DROP DATABASE IF EXISTS \"$TARGET\"" -c "CREATE DATABASE \"$TARGET\""
"${P[@]}" -d "$TARGET" -c "CREATE EXTENSION IF NOT EXISTS timescaledb" -c "SELECT timescaledb_pre_restore()" >/dev/null
docker exec -i "$CONTAINER" pg_restore -U market -d "$TARGET" --no-owner <"$DUMP" || true
"${P[@]}" -d "$TARGET" -c "SELECT timescaledb_post_restore()" >/dev/null

echo "Restored $DUMP -> $TARGET"
for t in ohlcv_1d ohlcv_1w ohlcv_1mo ta_daily signal swing_signals; do
  echo "  $t: $("${P[@]}" -d "$TARGET" -c "select count(*) from $t")"
done

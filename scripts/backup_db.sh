#!/usr/bin/env bash
# Nightly logical backup of the market database.
#   - Writes a compressed pg_dump to $BACKUP_DIR (default: ~/backups/vynzo), keeps $BACKUP_KEEP days
#   - Copies it off-host when BACKUP_REMOTE is set (rsync target, e.g. user@host:/path)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && { set -a; source "$ROOT/.env"; set +a; }

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/vynzo}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"
CONTAINER="${DB_CONTAINER:-timescaledb}"
mkdir -p "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/market_${STAMP}.dump"

echo "$(date -Is) backup start -> $OUT"
# Run pg_dump inside the DB container (matching server version); custom format = compressed
docker exec "$CONTAINER" pg_dump -U market -d market -Fc -Z 6 >"$OUT.partial"
mv "$OUT.partial" "$OUT"

# Sanity check: archive must list its contents
docker exec -i "$CONTAINER" pg_restore --list <"$OUT" >/dev/null
echo "$(date -Is) backup ok ($(du -h "$OUT" | cut -f1))"

find "$BACKUP_DIR" -name 'market_*.dump' -mtime +"$BACKUP_KEEP" -delete

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  rsync -a --delete --include='market_*.dump' --exclude='*' "$BACKUP_DIR/" "$BACKUP_REMOTE/"
  echo "$(date -Is) copied to $BACKUP_REMOTE"
fi

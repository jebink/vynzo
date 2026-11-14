#!/usr/bin/env bash
# SSH tunnel from this machine to the dev server's PostgreSQL/TimescaleDB (one server, one port).
#   scripts/tunnel.sh            # = start: localhost:5432 -> dev server's 127.0.0.1:5432
#   scripts/tunnel.sh start|stop|status|restart
#
# Settings (environment or .env): DEV_SSH (default admin@192.168.31.11), TUNNEL_LOCAL_PORT
# (default 5432), TUNNEL_REMOTE_PORT (default 5432). SSH asks for the password unless you
# have a key on the server (ssh-copy-id "$DEV_SSH"). No password is stored by this script.
#
# With the tunnel up, DATABASE_URL=postgresql://market:<dev password>@localhost:5432/market
# reaches dev: the API, workers, `make migrate` and the integration tests then act on the
# shared dev database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  # Only the tunnel settings: the rest of .env is not needed here.
  eval "$(grep -E '^(DEV_SSH|TUNNEL_LOCAL_PORT|TUNNEL_REMOTE_PORT)=' "$ROOT/.env" || true)"
fi
DEV_SSH="${DEV_SSH:-admin@192.168.31.11}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-5432}"
REMOTE_PORT="${TUNNEL_REMOTE_PORT:-5432}"
# Control socket: lets stop/status find this tunnel. Short path (macOS limit is 104 bytes).
SOCK="/tmp/vynzo-db-tunnel-${LOCAL_PORT}.sock"

port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$LOCAL_PORT") 2>/dev/null; }
running() { ssh -S "$SOCK" -O check "$DEV_SSH" 2>/dev/null; }

start() {
  if running; then
    echo "Tunnel already up: localhost:$LOCAL_PORT -> $DEV_SSH:$REMOTE_PORT"
    return 0
  fi
  rm -f "$SOCK"  # stale socket from a tunnel that died (sleep, network change)
  if port_open; then
    echo "localhost:$LOCAL_PORT is already in use by something else:" >&2
    lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >&2 || true
    echo "Stop it (e.g. a local database: make db-down) or set TUNNEL_LOCAL_PORT." >&2
    return 1
  fi
  echo "Opening tunnel localhost:$LOCAL_PORT -> $DEV_SSH:$REMOTE_PORT ..."
  ssh -f -N -M -S "$SOCK" \
    -o ControlPersist=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:$REMOTE_PORT" \
    "$DEV_SSH"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    port_open && { echo "Tunnel up. Database at localhost:$LOCAL_PORT (dev server)."; return 0; }
    sleep 0.5
  done
  echo "SSH connected but localhost:$LOCAL_PORT is not accepting connections." >&2
  return 1
}

stop() {
  if running; then
    ssh -S "$SOCK" -O exit "$DEV_SSH" 2>/dev/null
    echo "Tunnel closed."
  else
    echo "No tunnel running (from this script) on localhost:$LOCAL_PORT."
  fi
  rm -f "$SOCK"
}

status() {
  if running; then
    echo "Up: localhost:$LOCAL_PORT -> $DEV_SSH:$REMOTE_PORT"
  elif port_open; then
    echo "Not this script's tunnel, but something is listening on localhost:$LOCAL_PORT:"
    lsof -nP -iTCP:"$LOCAL_PORT" -sTCP:LISTEN || true
  else
    echo "Down. Start it with: scripts/tunnel.sh"
    return 1
  fi
}

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  restart) stop; start ;;
  *) echo "usage: scripts/tunnel.sh [start|stop|status|restart]" >&2; exit 2 ;;
esac

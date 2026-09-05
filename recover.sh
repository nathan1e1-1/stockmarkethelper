#!/bin/zsh
# Wait for the paper broker to become flat, then re-arm and restart the engine.
# The engine stays fail-closed (HALTED) until the broker reconciles cleanly, so this
# script just polls `--rearm` (which exits 0 only on success) and kicks launchd once it works.
#
# Usage: ./recover.sh [max_attempts]
#   default 100 attempts x 60s = ~100 minutes of waiting.

set -euo pipefail

ENGINE_DIR="/Users/nthnp/Developer/stockmarkethelper/engine"
LABEL="com.nathan1e1.stockmarkethelper.engine"
MAX_ATTEMPTS="${1:-100}"
INTERVAL_SECONDS=60
LOG="/tmp/recover-rearm.log"

cd "$ENGINE_DIR"

attempt=0
while (( attempt < MAX_ATTEMPTS )); do
  attempt=$((attempt + 1))
  echo "[recover] attempt $attempt/$MAX_ATTEMPTS: running --rearm"
  if PYTHONPATH="$ENGINE_DIR/src" .venv/bin/python -m autotrader.main --rearm >"$LOG" 2>&1; then
    echo "[recover] re-armed successfully"
    rm -f "$LOG"
    echo "[recover] restarting launchd engine: $LABEL"
    launchctl kickstart -k "gui/$(id -u)/$LABEL"
    echo "[recover] done"
    exit 0
  fi
  echo "[recover] not clean yet: $(tail -1 "$LOG")"
  sleep "$INTERVAL_SECONDS"
done

echo "[recover] gave up after $MAX_ATTEMPTS attempts; engine remains HALTED"
exit 1
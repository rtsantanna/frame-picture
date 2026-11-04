#!/usr/bin/env bash
# Frame Picture — canonical Dropbox->local sync (Missao Mestre, item 10/11).
#
# One flow shared by the cron schedule AND the panel's "Sincronizar agora"
# button, guarded by a single flock so the two can never run concurrently.
# Semantics are deliberately `rclone copy` (never `sync`): new remote files are
# pulled in; files deleted on Dropbox are NOT removed locally; local files are
# never pushed or deleted; no remote deletions ever happen.
#
# --ignore-existing is what keeps the Photo Optimizer safe: once a local file
# exists (even after we shrink it in place) rclone skips it, so an optimized
# photo is never re-downloaded to its larger original.
set -uo pipefail

PHOTOS="${PIC_DIR:-/data/photos}"
CONTROL="${FP_CONTROL_DIR:-/data/frame-picture/control}"
LOCKFILE="$CONTROL/sync.lock"
METRICS="$CONTROL/sync-metrics.json"
LOG="${FP_SYNC_LOG:-/var/log/framepicture-sync.log}"
REMOTE="${FP_RCLONE_REMOTE:-dropbox:}"
TRIGGER="$CONTROL/sync-request"

mkdir -p "$CONTROL" "$PHOTOS"

# Reason recorded in the metrics: "cron", "manual", ... (defaults to cron).
REASON="${1:-cron}"

# Single-flight: non-blocking lock. A second invocation (cron overlapping a
# manual run, or vice-versa) exits cleanly instead of racing.
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "$(date -Is) [$REASON] sync already running; skipped" >> "$LOG"
  exit 0
fi

write_metrics() {
  # $1 running(true/false) $2 result $3 new $4 total $5 duration $6 errors
  local tmp="$METRICS.tmp.$$"
  cat > "$tmp" <<JSON
{
  "running": $1,
  "result": "$2",
  "reason": "$REASON",
  "last_sync": "$(date -Is)",
  "last_sync_epoch": $(date +%s),
  "new_files": $3,
  "total_files": $4,
  "duration_s": $5,
  "errors": $6
}
JSON
  mv -f "$tmp" "$METRICS"
}

start=$(date +%s)
write_metrics true "running" 0 "$(find "$PHOTOS" -type f 2>/dev/null | wc -l)" 0 0

before=$(find "$PHOTOS" -type f 2>/dev/null | wc -l)
echo "$(date -Is) [$REASON] sync start (before=$before)" >> "$LOG"

# --- divergence detection (Missao 04 item 4) --------------------------------
# Snapshot the CURRENT remote metadata and compare it to the persistent
# manifest of what we last imported. This runs BEFORE the copy, so an
# updated-in-source file is flagged while rclone's --ignore-existing leaves the
# local (possibly optimized) copy untouched. Never fatal to the sync itself.
MANIFEST_PY="$(dirname "$0")/sync_manifest.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$MANIFEST_PY" ]; then
  if /usr/bin/rclone lsjson "$REMOTE" --hash --recursive > "$CONTROL/remote-now.json" 2>>"$LOG"; then
    python3 "$MANIFEST_PY" \
      "$CONTROL/remote-now.json" \
      "$CONTROL/dropbox-manifest.json" \
      "$CONTROL/sync-divergences.json" >> "$LOG" 2>&1 \
      || echo "$(date -Is) [$REASON] manifest comparison failed" >> "$LOG"
  else
    echo "$(date -Is) [$REASON] rclone lsjson failed; skipping divergence check" >> "$LOG"
  fi
fi

/usr/bin/rclone copy "$REMOTE" "$PHOTOS" \
  --ignore-existing --transfers 4 \
  --log-file "$LOG" --log-level INFO
rc=$?

after=$(find "$PHOTOS" -type f 2>/dev/null | wc -l)
end=$(date +%s)
dur=$(( end - start ))
new=$(( after - before )); [ "$new" -lt 0 ] && new=0
if [ "$rc" -eq 0 ]; then result="ok"; errors=0; else result="error"; errors=1; fi

write_metrics false "$result" "$new" "$after" "$dur" "$errors"
echo "$(date -Is) [$REASON] sync end rc=$rc new=$new total=$after dur=${dur}s" >> "$LOG"

# --- catalog rescan ---------------------------------------------------------
# The panel's catalog only learns about files through a rescan. When this run
# brought new files, flag a pending rescan; then try to trigger it through the
# local API. The flag is cleared only when the API answers "started", so a
# rescan missed because the container was down, or because a scan was already
# running ("busy"), is retried on the next run. Never fatal to the sync itself.
SCAN_PENDING="$CONTROL/catalog-scan-pending"
SCAN_URL="${FP_CATALOG_SCAN_URL:-http://127.0.0.1:9000/api/catalog/scan}"
[ "$new" -gt 0 ] && touch "$SCAN_PENDING"
if [ -f "$SCAN_PENDING" ]; then
  scan_resp=$(curl -s --max-time 10 -X POST "$SCAN_URL" 2>/dev/null || true)
  if printf '%s' "$scan_resp" | grep -q '"started"'; then
    rm -f "$SCAN_PENDING"
    echo "$(date -Is) [$REASON] catalog rescan started" >> "$LOG"
  else
    echo "$(date -Is) [$REASON] catalog rescan pending (api: ${scan_resp:-no response}); retry next run" >> "$LOG"
  fi
fi

# Consume a one-shot manual trigger if present (the panel drops this file).
rm -f "$TRIGGER" 2>/dev/null || true

exit "$rc"

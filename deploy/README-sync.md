# Frame Picture — Dropbox sync (host side)

Canonical sync flow shared by the schedule and the panel's "Sincronizar agora".

## Pieces
- `sync.sh` — the one flow. `flock` single-flight; `rclone copy` (never `sync`);
  `--ignore-existing` so optimized local files are never re-downloaded. Writes
  `control/sync-metrics.json` (running/result/last_sync/new_files/total_files/
  duration_s/errors). Deployed to `/data/frame-picture/sync.sh` (chmod +x).
- Schedule: crontab, every 10 minutes (no duplicate schedulers):
  `*/10 * * * * /data/frame-picture/sync.sh cron # framepicture-sync`
- On-demand: `systemd/framepicture-sync.path` watches
  `/data/frame-picture/control/sync-request`; when the panel drops that file
  (via the `./control` bind mount) `framepicture-sync.service` runs
  `sync.sh manual`. No Docker socket / shell exposed to the panel.

## Install (host)
```
install -m755 sync.sh /data/frame-picture/sync.sh
cp systemd/framepicture-sync.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now framepicture-sync.path
( crontab -l | grep -v framepicture-sync; \
  echo '*/10 * * * * /data/frame-picture/sync.sh cron # framepicture-sync' ) | crontab -
```

## Semantics (never changed automatically)
- New remote files -> pulled local. Remote deletions -> NOT removed locally.
- Local files never pushed/deleted. No remote deletions. Ever.

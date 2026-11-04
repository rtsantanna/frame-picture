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
- Catalog rescan: the panel's catalog only learns about files through a rescan.
  When a run brings new files, `sync.sh` drops `control/catalog-scan-pending`
  and calls `POST http://127.0.0.1:9000/api/catalog/scan` (override with
  `FP_CATALOG_SCAN_URL`). The flag is cleared only on `"started"`; if the
  container is down or a scan is already running (`"busy"`), the next run
  retries. Approvals and descriptions are kept by the rescan.

## Install (host)
```
install -m755 sync.sh /data/frame-picture/sync.sh
cp systemd/framepicture-sync.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now framepicture-sync.path
( crontab -l | grep -v framepicture-sync; \
  echo '*/10 * * * * /data/frame-picture/sync.sh cron # framepicture-sync' ) | crontab -
```

## Host boot settings (outside the container)
- Force HDMI-A-1 on at boot, so the compositor always has an output even when
  the TV was off/in standby at boot or drops hotplug during night mode
  (`display_power` off 00:00-06:00). Append to the single line of
  `/boot/firmware/cmdline.txt`, keeping it one line, then reboot:
  `video=HDMI-A-1:1920x1080@60D`
  Without it, picframe logs `failed to init sdl2: The video driver did not add
  any displays` / `Renderer blocked` and the HDMI stays black.
- The container uses `restart: unless-stopped` (`compose.yaml`), so it comes back
  on its own after a reboot; Docker itself is enabled in systemd.

## Semantics (never changed automatically)
- New remote files -> pulled local. Remote deletions -> NOT removed locally.
- Local files never pushed/deleted. No remote deletions. Ever.

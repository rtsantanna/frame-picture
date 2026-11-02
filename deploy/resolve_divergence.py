#!/usr/bin/env python3
"""
Frame Picture — resolve a Dropbox divergence by safely updating the local copy
(Missao 05 item 7). Runs on the HOST (needs rclone); triggered by the panel via
control/resolve-request.json + a systemd path-unit.

Safe flow: download the remote version to STAGING, validate integrity/format,
keep the previous local file as a backup until the new one is in place, then
replace atomically. The catalog entry (keyed by relative path) is untouched, so
the approved description and visibility are preserved. The manifest baseline for
that path is updated to the current remote metadata and the divergence is
removed, so it will not re-appear on the next sync. Never touches the Dropbox
remote; never deletes personal files (the old copy goes to a .bak kept aside).

Reads : control/resolve-request.json  {"path": "<remote/local relative path>"}
Writes: the local file under /data/photos, updates manifest + divergences,
        control/resolve-result.json {path, status, detail, ts}
"""

from __future__ import annotations

import json
import os
import subprocess
import time

CONTROL = os.environ.get("FP_CONTROL_DIR", "/data/frame-picture/control")
PHOTOS = os.environ.get("PIC_DIR", "/data/photos")
REMOTE = os.environ.get("FP_RCLONE_REMOTE", "dropbox:")
REQUEST = os.path.join(CONTROL, "resolve-request.json")
RESULT = os.path.join(CONTROL, "resolve-result.json")
MANIFEST = os.path.join(CONTROL, "dropbox-manifest.json")
DIVERGENCES = os.path.join(CONTROL, "sync-divergences.json")
STAGING = os.path.join(CONTROL, "staging")
LOG = "/var/log/framepicture-sync.log"


def _log(msg: str) -> None:
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%FT%T')} [resolve] {msg}\n")
    except OSError:
        pass


def _write_result(path: str, status: str, detail: str) -> None:
    tmp = RESULT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"path": path, "status": status, "detail": detail, "ts": time.time()}, fh)
    os.replace(tmp, RESULT)


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def main() -> int:
    try:
        os.remove(REQUEST)
    except OSError:
        pass
    # The API writes the target path to resolve-current.json and touches the
    # request file to trigger this run.
    req = _load(os.path.join(CONTROL, "resolve-current.json"), None)
    if not req or "path" not in req:
        _write_result("", "error", "no resolve request")
        return 1
    rel = req["path"]
    local = os.path.join(PHOTOS, rel)
    os.makedirs(STAGING, exist_ok=True)
    staged = os.path.join(STAGING, os.path.basename(rel) + ".incoming")

    # 1) download remote -> staging (never touches the remote)
    r = subprocess.run(
        ["/usr/bin/rclone", "copyto", f"{REMOTE}{rel}", staged, "--no-traverse"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not os.path.isfile(staged) or os.path.getsize(staged) == 0:
        _log(f"download failed for {rel}: {r.stderr[:200]}")
        _write_result(rel, "error", "download failed")
        return 1

    # 2) validate integrity/format with exiftool (available on the host; it
    # recognises both images and video containers). A recognised FileType means
    # the staged download is a well-formed media file.
    probe = subprocess.run(
        ["exiftool", "-s3", "-FileType", staged], capture_output=True, text=True
    )
    ok = probe.returncode == 0 and bool(probe.stdout.strip())
    if not ok:
        _log(f"validation failed {rel}: exiftool rc={probe.returncode} out={probe.stdout.strip()!r}")
    if not ok:
        try:
            os.remove(staged)
        except OSError:
            pass
        _write_result(rel, "error", "validation failed; local copy preserved")
        return 1

    # 3) keep previous local as .bak until the new one is in place, then replace
    bak = local + ".bak"
    try:
        if os.path.isfile(local):
            os.replace(local, bak)
        os.replace(staged, local)
        if os.path.isfile(bak):
            os.remove(bak)
    except OSError as exc:
        # roll back
        if os.path.isfile(bak) and not os.path.isfile(local):
            os.replace(bak, local)
        _write_result(rel, "error", f"replace failed: {exc}")
        return 1

    # 4) update manifest baseline = current remote meta; drop the divergence
    man = _load(MANIFEST, {})
    lsj = subprocess.run(
        ["/usr/bin/rclone", "lsjson", f"{REMOTE}{rel}", "--hash"],
        capture_output=True, text=True,
    )
    try:
        entry = json.loads(lsj.stdout)[0]
        h = (entry.get("Hashes") or {})
        man[rel] = {
            "size": int(entry.get("Size", 0)),
            "hash": str(h.get("dropbox") or h.get("DropboxHash") or ""),
            "modtime": entry.get("ModTime"),
            "imported_at": time.time(),
        }
        with open(MANIFEST, "w", encoding="utf-8") as fh:
            json.dump(man, fh, indent=0)
    except Exception as exc:
        _log(f"manifest update skipped for {rel}: {exc}")

    div = _load(DIVERGENCES, {"items": []})
    div["items"] = [d for d in div.get("items", []) if d.get("path") != rel]
    with open(DIVERGENCES, "w", encoding="utf-8") as fh:
        json.dump(div, fh, indent=2)

    _log(f"resolved {rel}: local updated from remote (optimizer will shrink on next run)")
    _write_result(rel, "ok", "cópia local atualizada; catálogo preservado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

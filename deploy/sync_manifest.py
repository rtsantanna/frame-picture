#!/usr/bin/env python3
"""
Dropbox divergence detector (Missao 04 item 4).

Compares the CURRENT remote listing (``rclone lsjson --hash``) against a
persistent manifest of the remote metadata we last imported — NOT against the
local files, which legitimately differ after the Photo Optimizer rewrites them.
This is what lets us tell "remote unchanged, local optimized" (normal) apart
from "remote updated with the same name" (a divergence that must not be applied
silently).

Writes:
- divergences.json : {generated_at, items:[{path, status, remote_size,
  remote_hash, remote_modtime, baseline_size, baseline_hash, detected_at}]}
- manifest.json    : {path: {size, hash, modtime, imported_at}} updated so NEW
  files (which rclone will import right after) become the new baseline, while
  DIVERGED files keep their old baseline so the divergence persists until the
  operator resolves it.

Statuses: ``new`` (import), ``unchanged``, ``updated_source`` (divergence),
``absent_source`` (gone from Dropbox — never auto-deleted locally).

Usage: sync_manifest.py <remote-now.json> <manifest.json> <divergences.json>
"""

from __future__ import annotations

import json
import sys
import time


def _hash_of(entry: dict) -> str:
    h = entry.get("Hashes") or {}
    # rclone exposes the Dropbox content hash under one of these keys.
    return str(h.get("dropbox") or h.get("DropboxHash") or h.get("dropbox_hash") or "")


def main() -> int:
    remote_path, manifest_path, div_path = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(remote_path, encoding="utf-8") as fh:
        remote_list = json.load(fh)
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        manifest = {}

    now = time.time()
    remote_by_path: dict[str, dict] = {}
    for e in remote_list:
        if e.get("IsDir"):
            continue
        remote_by_path[e["Path"]] = e

    divergences: list[dict] = []
    new_manifest = dict(manifest)

    for path, e in remote_by_path.items():
        size = int(e.get("Size", -1))
        rhash = _hash_of(e)
        modtime = e.get("ModTime")
        base = manifest.get(path)
        if base is None:
            # New remote file: rclone copy will import it right after; record the
            # current remote metadata as the baseline.
            new_manifest[path] = {
                "size": size, "hash": rhash, "modtime": modtime, "imported_at": now,
            }
            continue
        changed = (rhash and base.get("hash") and rhash != base["hash"]) or (
            (not rhash or not base.get("hash")) and size != base.get("size")
        )
        if changed:
            # Remote changed under the same name -> divergence. Keep the old
            # baseline so the divergence stays visible until resolved.
            divergences.append({
                "path": path,
                "status": "updated_source",
                "remote_size": size,
                "remote_hash": rhash,
                "remote_modtime": modtime,
                "baseline_size": base.get("size"),
                "baseline_hash": base.get("hash"),
                "detected_at": now,
            })

    for path, base in manifest.items():
        if path not in remote_by_path:
            divergences.append({
                "path": path,
                "status": "absent_source",
                "remote_size": None,
                "remote_hash": None,
                "remote_modtime": None,
                "baseline_size": base.get("size"),
                "baseline_hash": base.get("hash"),
                "detected_at": now,
            })

    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(new_manifest, fh, indent=0)
    with open(div_path, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": now, "items": divergences}, fh, indent=2)

    print(f"manifest={len(new_manifest)} divergences={len(divergences)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

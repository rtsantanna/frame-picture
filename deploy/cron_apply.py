#!/usr/bin/env python3
"""
Frame Picture — apply the Dropbox-sync crontab entry from the web panel
(Missao 05 item 5). Runs on the HOST, triggered by a systemd path-unit when the
panel drops ``control/cron-request``. It edits ONLY the Frame Picture sync line
(marked ``# framepicture-sync``), never other crontab entries, and never runs
arbitrary shell — the command is fixed, only the schedule changes.

Reads  : control/cron-config.json  {"enabled": bool, "cron": "<expr>"}
Writes : the real user crontab (framepicture-sync line) + control/cron-state.json
         {"enabled", "cron", "command", "applied_at", "next_run", "error"}

The cron expression must match one of the allowed presets or a validated
``*/N * * * *`` / simple form — not an arbitrary string.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CONTROL = os.environ.get("FP_CONTROL_DIR", "/data/frame-picture/control")
CONFIG = os.path.join(CONTROL, "cron-config.json")
STATE = os.path.join(CONTROL, "cron-state.json")
REQUEST = os.path.join(CONTROL, "cron-request")
MARKER = "# framepicture-sync"
COMMAND = "/data/frame-picture/sync.sh cron"
TZ = ZoneInfo("America/Sao_Paulo")

# Allowed schedules (preset label -> cron expression).
PRESETS = {
    "5m": "*/5 * * * *", "10m": "*/10 * * * *", "15m": "*/15 * * * *",
    "30m": "*/30 * * * *", "1h": "0 * * * *", "2h": "0 */2 * * *",
    "6h": "0 */6 * * *", "12h": "0 */12 * * *", "24h": "0 0 * * *",
}
# A conservative validator: 5 fields, each a number, *, */N, or a/b list — no
# shell metacharacters. This is a schedule, never a command.
_FIELD = re.compile(r"^(\*|\d+|\*/\d+|\d+(,\d+)*|\d+-\d+)$")


def validate_cron(expr: str) -> str | None:
    expr = expr.strip()
    if expr in PRESETS.values():
        return expr
    parts = expr.split()
    if len(parts) != 5:
        return None
    if all(_FIELD.match(p) for p in parts):
        return expr
    return None


def read_crontab() -> list[str]:
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return r.stdout.splitlines()


def write_crontab(lines: list[str]) -> None:
    data = ("\n".join(lines) + "\n") if lines else "\n"
    subprocess.run(["crontab", "-"], input=data, text=True, check=True)


def next_run(expr: str, now: datetime) -> str | None:
    """Best-effort next-run for the presets (minute/hour step forms)."""
    parts = expr.split()
    if len(parts) != 5:
        return None
    minute, hour = parts[0], parts[1]
    cand = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(0, 60 * 24 * 2):  # scan up to 2 days
        if _match_field(minute, cand.minute) and _match_field(hour, cand.hour):
            return cand.isoformat()
        cand += timedelta(minutes=1)
    return None


def _match_field(field: str, value: int) -> bool:
    if field == "*":
        return True
    if field.startswith("*/"):
        return value % int(field[2:]) == 0
    if "," in field:
        return value in {int(x) for x in field.split(",")}
    if "-" in field:
        a, b = field.split("-")
        return int(a) <= value <= int(b)
    return value == int(field)


def write_state(**kw) -> None:
    kw["applied_at"] = time.time()
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(kw, fh, indent=2)
    os.replace(tmp, STATE)


def main() -> int:
    # Consume the one-shot trigger so the path-unit can fire again next time.
    try:
        os.remove(REQUEST)
    except OSError:
        pass
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as exc:
        write_state(enabled=None, cron=None, command=COMMAND, next_run=None,
                    error=f"cron-config unreadable: {exc}")
        return 1

    enabled = bool(cfg.get("enabled", True))
    expr = validate_cron(str(cfg.get("cron", "*/10 * * * *")))
    if expr is None:
        write_state(enabled=enabled, cron=cfg.get("cron"), command=COMMAND,
                    next_run=None, error="invalid cron expression (rejected)")
        return 1

    # Rebuild the crontab: drop our old line, keep everyone else's, add ours.
    lines = [ln for ln in read_crontab() if MARKER not in ln]
    if enabled:
        lines.append(f"{expr} {COMMAND} {MARKER}")
    try:
        write_crontab(lines)
    except subprocess.CalledProcessError as exc:
        write_state(enabled=enabled, cron=expr, command=COMMAND, next_run=None,
                    error=f"crontab write failed: {exc}")
        return 1

    nr = next_run(expr, datetime.now(TZ)) if enabled else None
    write_state(enabled=enabled, cron=expr, command=COMMAND, next_run=nr, error=None)
    print(f"applied enabled={enabled} cron={expr!r} next_run={nr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

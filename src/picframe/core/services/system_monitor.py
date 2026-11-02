"""
System monitor (Missao 05 item 8).

Reads REAL host and container metrics without a Docker socket: host CPU/RAM/
swap/temp/uptime/load/disk from ``/proc`` and ``/sys`` (network_mode host, so
these reflect the Pi), and container CPU/RAM from cgroups v2
(``/sys/fs/cgroup``) — never the bogus ``docker stats = 0B``. Anything that
cannot be read is reported as ``None`` so the panel can show "Indisponível"
instead of inventing a zero.
"""

from __future__ import annotations

import os
import time
from typing import Any

_CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def _cpu_times() -> tuple[int, int] | None:
    data = _read("/proc/stat")
    if not data:
        return None
    for line in data.splitlines():
        if line.startswith("cpu "):
            parts = [int(x) for x in line.split()[1:]]
            idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
            total = sum(parts)
            return total, idle
    return None


def _host_cpu_percent(interval: float = 0.2) -> float | None:
    a = _cpu_times()
    if not a:
        return None
    time.sleep(interval)
    b = _cpu_times()
    if not b:
        return None
    dt = b[0] - a[0]
    di = b[1] - a[1]
    if dt <= 0:
        return None
    return round(100.0 * (dt - di) / dt, 1)


def _meminfo() -> dict[str, int]:
    out: dict[str, int] = {}
    data = _read("/proc/meminfo") or ""
    for line in data.splitlines():
        k, _, rest = line.partition(":")
        try:
            out[k.strip()] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
        except (ValueError, IndexError):
            pass
    return out


def _temp_c() -> float | None:
    for zone in ("thermal_zone0", "thermal_zone1"):
        raw = _read(f"/sys/class/thermal/{zone}/temp")
        if raw and raw.strip().lstrip("-").isdigit():
            return round(int(raw.strip()) / 1000.0, 1)
    return None


def _uptime_s() -> float | None:
    raw = _read("/proc/uptime")
    if not raw:
        return None
    try:
        return float(raw.split()[0])
    except (ValueError, IndexError):
        return None


def _loadavg() -> list[float] | None:
    raw = _read("/proc/loadavg")
    if not raw:
        return None
    try:
        return [float(x) for x in raw.split()[:3]]
    except ValueError:
        return None


def _disk(path: str = "/data/photos") -> dict[str, int] | None:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total": total, "free": free, "used": total - free}


def _cgroup_mem() -> int | None:
    raw = _read("/sys/fs/cgroup/memory.current")
    if raw and raw.strip().isdigit():
        return int(raw.strip())
    return None


def _cgroup_cpu_usec() -> int | None:
    data = _read("/sys/fs/cgroup/cpu.stat")
    if not data:
        return None
    for line in data.splitlines():
        if line.startswith("usage_usec"):
            try:
                return int(line.split()[1])
            except (ValueError, IndexError):
                return None
    return None


def _container_cpu_percent(interval: float = 0.2) -> float | None:
    a = _cgroup_cpu_usec()
    if a is None:
        return None
    time.sleep(interval)
    b = _cgroup_cpu_usec()
    if b is None:
        return None
    ncpu = os.cpu_count() or 1
    busy = (b - a) / 1_000_000.0  # usec -> sec of CPU time
    return round(100.0 * busy / (interval * ncpu), 1)


def collect() -> dict[str, Any]:
    """Collect a full metrics snapshot. ~0.4s (two short CPU deltas)."""
    mem = _meminfo()
    mem_total = mem.get("MemTotal")
    mem_avail = mem.get("MemAvailable")
    swap_total = mem.get("SwapTotal")
    swap_free = mem.get("SwapFree")
    host = {
        "cpu_percent": _host_cpu_percent(),
        "cpu_count": os.cpu_count(),
        "mem_total": mem_total,
        "mem_available": mem_avail,
        "mem_used": (mem_total - mem_avail) if (mem_total and mem_avail is not None) else None,
        "swap_total": swap_total,
        "swap_used": (swap_total - swap_free) if (swap_total and swap_free is not None) else None,
        "temp_c": _temp_c(),
        "uptime_s": _uptime_s(),
        "loadavg": _loadavg(),
        "disk": _disk(),
    }
    container = {
        "cpu_percent": _container_cpu_percent(),
        "mem_used": _cgroup_mem(),
    }
    return {"host": host, "container": container, "collected_at": time.time()}

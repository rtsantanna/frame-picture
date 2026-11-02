"""
Night standby scheduler (Missao Mestre item 12).

Puts the HDMI output into standby during a configurable nightly window
(default 00:00-06:00, America/Sao_Paulo) by publishing the existing
``DISPLAY_OFF`` / ``DISPLAY_ON`` commands — which already drive the Wayland
output power AND pause/resume the slideshow queue, so the queue does not
advance while the screen is off. The Raspberry, Docker and Home Assistant are
never touched.

A one-night "keep the monitor on tonight" exception is persisted (survives a
container restart) and expires automatically at the end of that night's window.
On startup the scheduler reconciles immediately, so a container that restarts
inside the night window drives the screen back to the correct state.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from picframe.core.events.dto import Command, CommandEvent
from picframe.core.events.interfaces import IEventPublisher
from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")

CFG_ENABLED = "night.enabled"
CFG_OFF = "night.off_time"
CFG_ON = "night.on_time"
CFG_KEEP_ON_UNTIL = "night.keep_on_until"  # epoch seconds; 0 = no exception

DEFAULT_OFF = "00:00"
DEFAULT_ON = "06:00"

_TICK_SECONDS = 20.0


def _parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
    try:
        h, m = str(value or fallback).split(":")
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except (ValueError, AttributeError):
        h, m = fallback.split(":")
        return int(h), int(m)


class NightSchedulerService:
    def __init__(
        self,
        event_publisher: IEventPublisher,
        config_repository: IConfigRepository,
    ) -> None:
        self._pub = event_publisher
        self._config = config_repository
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Last power state we COMMANDED (None = unknown/not yet reconciled).
        self._commanded_on: bool | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="NightScheduler", daemon=True)
        self._thread.start()
        logger.info("NightSchedulerService started.")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Reconcile once immediately (handles restart inside the window).
        self._reconcile(force=True)
        while not self._stop.wait(_TICK_SECONDS):
            try:
                self._reconcile()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Night scheduler tick failed: %s", exc)

    # -- config ------------------------------------------------------------

    def _cfg(self) -> dict:
        return {
            "enabled": self._config.get_app_config_bool(CFG_ENABLED, False),
            "off_time": str(self._config.get_app_config(CFG_OFF) or DEFAULT_OFF),
            "on_time": str(self._config.get_app_config(CFG_ON) or DEFAULT_ON),
            "keep_on_until": float(self._config.get_app_config(CFG_KEEP_ON_UNTIL) or 0),
        }

    def get_settings(self) -> dict:
        c = self._cfg()
        now = datetime.now(TZ)
        in_window = self._in_off_window(now, c["off_time"], c["on_time"])
        exception_active = self._exception_active(c["keep_on_until"], now)
        next_off, next_on = self._next_transitions(now, c["off_time"], c["on_time"])
        hdmi_should_be_on = (not c["enabled"]) or (not in_window) or exception_active
        return {
            "enabled": c["enabled"],
            "off_time": c["off_time"],
            "on_time": c["on_time"],
            "in_off_window": in_window,
            "exception_active": exception_active,
            "keep_on_until": c["keep_on_until"],
            "hdmi_on": self._commanded_on if self._commanded_on is not None else hdmi_should_be_on,
            "next_off": next_off.isoformat(),
            "next_on": next_on.isoformat(),
            "timezone": "America/Sao_Paulo",
        }

    def set_settings(
        self,
        enabled: bool | None = None,
        off_time: str | None = None,
        on_time: str | None = None,
    ) -> dict:
        if enabled is not None:
            self._config.set_app_config(CFG_ENABLED, bool(enabled))
        if off_time is not None:
            h, m = _parse_hhmm(off_time, DEFAULT_OFF)
            self._config.set_app_config(CFG_OFF, f"{h:02d}:{m:02d}")
        if on_time is not None:
            h, m = _parse_hhmm(on_time, DEFAULT_ON)
            self._config.set_app_config(CFG_ON, f"{h:02d}:{m:02d}")
        self._reconcile(force=True)
        return self.get_settings()

    def keep_on_tonight(self, enable: bool = True) -> dict:
        """Set/clear the one-night exception. When enabled it keeps the screen on
        until the end of the current/next night window, then auto-expires."""
        if not enable:
            self._config.set_app_config(CFG_KEEP_ON_UNTIL, 0)
        else:
            now = datetime.now(TZ)
            c = self._cfg()
            # The exception should cover THIS night: keep on until the window's
            # ending on_time boundary (the next on_time that closes a window).
            _next_off, next_on = self._next_transitions(now, c["off_time"], c["on_time"])
            # If we're already inside the window, next_on closes it; otherwise the
            # window starts at next_off and closes at the on_time after it.
            if self._in_off_window(now, c["off_time"], c["on_time"]):
                until = next_on
            else:
                oh, om = _parse_hhmm(c["on_time"], DEFAULT_ON)
                until = _next_off = self._next_transitions(now, c["off_time"], c["on_time"])[0]
                until = until.replace(hour=oh, minute=om, second=0, microsecond=0)
                if until <= _next_off:
                    until = until + timedelta(days=1)
            self._config.set_app_config(CFG_KEEP_ON_UNTIL, until.timestamp())
        self._reconcile(force=True)
        return self.get_settings()

    # -- core evaluation ---------------------------------------------------

    @staticmethod
    def _in_off_window(now: datetime, off_time: str, on_time: str) -> bool:
        oh, om = _parse_hhmm(off_time, DEFAULT_OFF)
        nh, nm = _parse_hhmm(on_time, DEFAULT_ON)
        cur = now.hour * 60 + now.minute
        off = oh * 60 + om
        on = nh * 60 + nm
        if off == on:
            return False
        if off < on:
            return off <= cur < on
        # window wraps past midnight (e.g. 23:00 -> 06:00)
        return cur >= off or cur < on

    @staticmethod
    def _next_transitions(
        now: datetime, off_time: str, on_time: str
    ) -> tuple[datetime, datetime]:
        oh, om = _parse_hhmm(off_time, DEFAULT_OFF)
        nh, nm = _parse_hhmm(on_time, DEFAULT_ON)

        def _next(h: int, m: int) -> datetime:
            cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if cand <= now:
                cand += timedelta(days=1)
            return cand

        return _next(oh, om), _next(nh, nm)

    def _exception_active(self, keep_on_until: float, now: datetime) -> bool:
        return keep_on_until > 0 and now.timestamp() < keep_on_until

    def _reconcile(self, force: bool = False) -> None:
        c = self._cfg()
        now = datetime.now(TZ)
        # Auto-expire a stale exception.
        if c["keep_on_until"] and now.timestamp() >= c["keep_on_until"]:
            self._config.set_app_config(CFG_KEEP_ON_UNTIL, 0)
            c["keep_on_until"] = 0
        exception = self._exception_active(c["keep_on_until"], now)
        in_window = self._in_off_window(now, c["off_time"], c["on_time"])
        should_be_on = (not c["enabled"]) or (not in_window) or exception
        if force or self._commanded_on != should_be_on:
            self._command(should_be_on)

    def _command(self, power_on: bool) -> None:
        cmd = Command.DISPLAY_ON if power_on else Command.DISPLAY_OFF
        try:
            self._pub.publish(CommandEvent(command=cmd))
            self._commanded_on = power_on
            logger.info("NightScheduler commanded display %s", "ON" if power_on else "OFF")
        except Exception as exc:  # pragma: no cover
            logger.warning("NightScheduler could not publish %s: %s", cmd, exc)

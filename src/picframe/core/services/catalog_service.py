"""
CatalogService — the brain of the "Catalogo de Memorias".

Scans ``model.pic_dir``, extracts metadata with exiftool (photos AND video
containers in one pass), derives locality suggestions in layers (GPS reverse
geocoding when explicitly enabled, else the filename), and exposes the dashboard
stats, the filtered/paginated listing and the individual/batch approval
operations the web panel drives.

Durability: every human decision lives in ``catalog.db3`` (see
:mod:`sqlite_catalog`). Rescans only refresh extracted metadata; approvals are
never overwritten. External geocoding is OFF by default and never sends image
content — only coordinates, and only when the operator turns it on.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from typing import Any

from picframe.core.repositories.interfaces import IConfigRepository
from picframe.core.repositories.sqlite_catalog import SQLiteCatalogRepository

logger = logging.getLogger(__name__)

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}
SUPPORTED_EXT = PHOTO_EXT | VIDEO_EXT

CFG_PIC_DIR = "model.pic_dir"
CFG_GEOCODE = "catalog.geocode_enabled"
CFG_SHOW_UNAPPROVED = "catalog.show_unapproved_on_hdmi"

_ORIENTATION = {
    1: "Normal", 2: "Mirror H", 3: "180", 4: "Mirror V",
    5: "Mirror H+270", 6: "90 CW", 7: "Mirror H+90", 8: "270 CW",
}

# Filename tokens that are camera noise, not a place/event description.
_STOPWORDS = {"file", "image", "photo", "picture", "img", "dsc", "dscn", "sam",
              "vid", "mov", "pict", "gopr", "dji", "untitled", "copy"}
_CAMERA_CODE = re.compile(r"^(IMG|DSC|DSCN|SAM|P|PICT|VID|MOV|GOPR|DJI|MVI)[ _-]?\d*$", re.I)
_LEADING_DATE = re.compile(
    r"^\s*\d{4}[-_]?\d{2}[-_]?\d{2}([ _-]?\d{2}[:_-]?\d{2}([:_-]?\d{2})?)?\s*[-_ ]*"
)
_TRAILING_SEQ = re.compile(r"[ _-]*\(?\d+\)?\s*$")


def suggest_from_filename(name: str) -> tuple[str | None, str, str]:
    """Derive a locality/event suggestion from a filename.

    Returns ``(suggestion|None, source, confidence)``. Conservative: a bare
    camera code (``SAM_0046``), a pure timestamp or a stop-word yields no
    suggestion rather than a misleading one.
    """
    base = os.path.splitext(name)[0]
    if _CAMERA_CODE.match(base):
        return None, "none", "low"
    base = _LEADING_DATE.sub("", base)
    base = _TRAILING_SEQ.sub("", base)
    if _CAMERA_CODE.match(base):
        return None, "none", "low"
    cleaned = re.sub(r"[_]+", " ", base).strip(" -_")
    if not cleaned or re.match(r"^[\d\W]+$", cleaned):
        return None, "none", "low"
    if cleaned.lower() in _STOPWORDS:
        return None, "none", "low"
    return cleaned, "filename", "medium"


class CatalogService:
    def __init__(
        self,
        catalog_repo: SQLiteCatalogRepository,
        config_repository: IConfigRepository,
    ) -> None:
        self._repo = catalog_repo
        self._config = config_repository
        self._lock = threading.Lock()
        self._scanning = False
        self._last_scan: float | None = None
        self._last_scan_result: dict[str, Any] | None = None

    # -- config ------------------------------------------------------------

    def pic_dir(self) -> str:
        return str(self._config.get_app_config(CFG_PIC_DIR) or "/data/photos")

    def get_settings(self) -> dict[str, Any]:
        return {
            "geocode_enabled": self._config.get_app_config_bool(CFG_GEOCODE, False),
            "show_unapproved_on_hdmi": self._config.get_app_config_bool(
                CFG_SHOW_UNAPPROVED, False
            ),
            "pic_dir": self.pic_dir(),
        }

    def set_settings(
        self, geocode_enabled: bool | None = None, show_unapproved_on_hdmi: bool | None = None
    ) -> dict[str, Any]:
        if geocode_enabled is not None:
            self._config.set_app_config(CFG_GEOCODE, bool(geocode_enabled))
        if show_unapproved_on_hdmi is not None:
            self._config.set_app_config(CFG_SHOW_UNAPPROVED, bool(show_unapproved_on_hdmi))
        return self.get_settings()

    # -- scanning ----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "scanning": self._scanning,
                "last_scan": self._last_scan,
                "last_scan_result": self._last_scan_result,
            }

    def start_scan_async(self) -> bool:
        with self._lock:
            if self._scanning:
                return False
            self._scanning = True
        threading.Thread(target=self._scan_thread, name="CatalogScan", daemon=True).start()
        return True

    def _scan_thread(self) -> None:
        try:
            result = self.scan()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Catalog scan failed: %s", exc)
            result = {"error": str(exc)}
        with self._lock:
            self._scanning = False
            self._last_scan = time.time()
            self._last_scan_result = result

    def scan(self) -> dict[str, Any]:
        """Walk the library, (re)extract metadata and refresh suggestions."""
        root = self.pic_dir()
        if not root or not os.path.isdir(root):
            return {"error": f"pic_dir not found: {root!r}", "indexed": 0}
        files = self._collect(root)
        extracted = self._exiftool(files) if files else {}
        geocode_on = self._config.get_app_config_bool(CFG_GEOCODE, False)
        indexed = 0
        for path in files:
            rel = os.path.relpath(path, root)
            meta = self._to_meta(path, extracted.get(path, {}))
            self._repo.upsert_scanned(rel, meta)
            self._apply_suggestion(rel, meta, geocode_on)
            indexed += 1
        return {
            "indexed": indexed,
            "photos": sum(1 for p in files if os.path.splitext(p)[1].lower() in PHOTO_EXT),
            "videos": sum(1 for p in files if os.path.splitext(p)[1].lower() in VIDEO_EXT),
        }

    @staticmethod
    def _collect(root: str) -> list[str]:
        out: list[str] = []
        for dp, _dirs, files in os.walk(root):
            for name in sorted(files):
                if name.startswith(".fp_opt_"):
                    continue
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXT:
                    out.append(os.path.join(dp, name))
        return out

    @staticmethod
    def _exiftool(files: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-extract metadata. Keyed by absolute SourceFile path."""
        tags = [
            "-FileName", "-MIMEType", "-FileType", "-FileSize#",
            "-DateTimeOriginal", "-CreateDate", "-DateTimeDigitized",
            "-MediaCreateDate", "-TrackCreateDate",
            "-OffsetTimeOriginal", "-OffsetTime",
            "-Make", "-Model", "-Orientation#",
            "-GPSLatitude", "-GPSLongitude", "-GPSAltitude",
            "-ImageWidth", "-ImageHeight", "-Duration#",
        ]
        try:
            proc = subprocess.run(
                ["exiftool", "-json", "-n", "-api", "largefilesupport=1", *tags, *files],
                capture_output=True, text=True, timeout=600,
            )
            data = json.loads(proc.stdout or "[]")
        except FileNotFoundError:
            logger.warning("exiftool not installed; catalog metadata will be sparse")
            return {}
        except Exception as exc:  # pragma: no cover
            logger.warning("exiftool extraction failed: %s", exc)
            return {}
        return {d.get("SourceFile", ""): d for d in data}

    def _to_meta(self, path: str, ex: dict[str, Any]) -> dict[str, Any]:
        ext = os.path.splitext(path)[1].lower()
        is_video = ext in VIDEO_EXT
        def pick(*keys: str) -> Any:
            for k in keys:
                v = ex.get(k)
                if v not in (None, "", "0000:00:00 00:00:00"):
                    return v
            return None
        if is_video:
            cap = pick("MediaCreateDate", "CreateDate", "TrackCreateDate", "DateTimeOriginal")
            date_source = "container" if cap else "none"
        else:
            cap = pick("DateTimeOriginal", "DateTimeDigitized", "CreateDate")
            date_source = "exif" if cap else "none"
        lat, lon = ex.get("GPSLatitude"), ex.get("GPSLongitude")
        try:
            if lat is not None and lon is not None and not (float(lat) == 0 and float(lon) == 0):
                lat, lon = round(float(lat), 6), round(float(lon), 6)
            else:
                lat = lon = None
        except (TypeError, ValueError):
            lat = lon = None
        orient = ex.get("Orientation")
        try:
            size = os.path.getsize(path)
            mtime = os.path.getmtime(path)
        except OSError:
            size = mtime = None
        return {
            "filename": os.path.basename(path),
            "media_type": "video" if is_video else "photo",
            "mime": ex.get("MIMEType"),
            "filetype": ex.get("FileType"),
            "capture_date": cap,
            "date_source": date_source,
            "tz_offset": pick("OffsetTimeOriginal", "OffsetTime"),
            "gps_lat": lat,
            "gps_lon": lon,
            "gps_alt": ex.get("GPSAltitude"),
            "make": pick("Make"),
            "model": pick("Model"),
            "orientation": _ORIENTATION.get(orient, str(orient) if orient is not None else None),
            "width": ex.get("ImageWidth"),
            "height": ex.get("ImageHeight"),
            "duration_s": ex.get("Duration") if is_video else None,
            "file_size": size,
            "file_mtime": mtime,
        }

    def _apply_suggestion(self, rel: str, meta: dict[str, Any], geocode_on: bool) -> None:
        # Layer 1: GPS reverse geocoding (only when explicitly enabled; never
        # sends image content, only coordinates; cached).
        if geocode_on and meta.get("gps_lat") is not None:
            place = self._reverse_geocode(meta["gps_lat"], meta["gps_lon"])
            if place:
                self._repo.set_suggestion(rel, place, "gps", "high")
                return
        # Layer 2: filename.
        sug, source, conf = suggest_from_filename(meta["filename"])
        if sug:
            self._repo.set_suggestion(rel, sug, source, conf)
        else:
            self._repo.set_suggestion(rel, "", "none", "low")

    def _reverse_geocode(self, lat: float, lon: float) -> str | None:
        """Reverse geocode coordinates -> "Cidade, Estado" via OpenStreetMap
        Nominatim. Only runs when ``catalog.geocode_enabled`` is on. Sends ONLY
        the coordinates (never image content), caches every result persistently
        (including "no result"), and rate-limits to Nominatim's 1 req/s policy.
        Returns a city/town/municipality — never a presumed tourist landmark."""
        import json as _json
        import time as _time
        import urllib.parse
        import urllib.request

        cached = self._repo.get_geocode(lat, lon)
        if cached is not None:
            return cached or None  # "" = looked up, no result
        params = urllib.parse.urlencode(
            {
                "format": "jsonv2",
                "lat": f"{lat:.5f}",
                "lon": f"{lon:.5f}",
                "zoom": "10",  # city level, not building/landmark
                "accept-language": "pt-BR",
            }
        )
        url = "https://nominatim.openstreetmap.org/reverse?" + params
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "FramePicture/1.0 (digital photo frame; rtsantanna)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            addr = data.get("address", {}) if isinstance(data, dict) else {}
            place = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("municipality")
                or addr.get("county")
            )
            state = addr.get("state")
            result = ", ".join([p for p in (place, state) if p]) if place else ""
            self._repo.set_geocode(lat, lon, result)
            _time.sleep(1.1)  # honour Nominatim's max 1 req/s
            return result or None
        except Exception as exc:
            logger.warning("Reverse geocode failed for %s,%s: %s", lat, lon, exc)
            return None

    # -- reads for the panel ----------------------------------------------

    def stats(self) -> dict[str, int]:
        s = self._repo.stats()
        total = s.get("total", 0)
        s["approval_pct"] = round(100 * s.get("approved", 0) / total) if total else 0
        return s

    def list(self, **kw: Any) -> dict[str, Any]:
        rows, total = self._repo.list(**kw)
        return {"items": rows, "total": total}

    def get(self, rel_path: str) -> dict[str, Any] | None:
        return self._repo.get(rel_path)

    # -- writes (approval) -------------------------------------------------

    def update(
        self, rel_path: str, fields: dict[str, Any], origin: str = "manual",
        batch_id: str | None = None,
    ) -> bool:
        if "approved_description" in fields:
            fields.setdefault("edited_manually", 1)
        before = self._repo.get(rel_path) or {}
        ok = self._repo.update_fields(rel_path, fields)
        if ok:
            self._record_changes(rel_path, before, fields, origin, batch_id)
        return ok

    def _record_changes(
        self, rel_path: str, before: dict[str, Any], fields: dict[str, Any],
        origin: str, batch_id: str | None,
    ) -> None:
        """Write a history event per meaningful field change."""
        if "approved_description" in fields:
            old = before.get("approved_description")
            new = fields["approved_description"]
            if old != new:
                event = "description_created" if not old else "description_edited"
                self._repo.add_event(rel_path, event, "approved_description", old, new,
                                     origin, batch_id)
        if "status" in fields and before.get("status") != fields["status"]:
            ev = {"approved": "approved", "review": "marked_review",
                  "pending": "unapproved"}.get(fields["status"], "status_changed")
            self._repo.add_event(rel_path, ev, "status", before.get("status"),
                                 fields["status"], origin, batch_id)
        if "visible" in fields and before.get("visible") != fields["visible"]:
            ev = "hidden" if fields["visible"] == 0 else "shown"
            self._repo.add_event(rel_path, ev, "visible", before.get("visible"),
                                 fields["visible"], origin, batch_id)
        if "suggestion" in fields and before.get("suggestion") != fields.get("suggestion"):
            self._repo.add_event(rel_path, "suggestion_changed", "suggestion",
                                 before.get("suggestion"), fields.get("suggestion"),
                                 origin, batch_id)

    def get_history(self, rel_path: str) -> list[dict[str, Any]]:
        return self._repo.get_history(rel_path)

    def batch(
        self,
        rel_paths: list[str],
        action: str,
        description: str | None = None,
        overwrite_approved: bool = False,
    ) -> dict[str, Any]:
        """Apply a batch action. Returns a preview-style summary of what changed.

        Approved descriptions are protected: ``set_description`` skips already
        approved rows unless ``overwrite_approved`` is set. Rows whose only
        suggestion is "no info" are ignored by ``approve_suggestion``.
        """
        changed = skipped = ignored = 0
        bid = uuid.uuid4().hex[:12]
        for rel in rel_paths:
            row = self._repo.get(rel)
            if row is None:
                continue
            if action == "set_description":
                if row["status"] == "approved" and not overwrite_approved:
                    skipped += 1
                    continue
                self.update(
                    rel,
                    {"approved_description": description, "status": "approved",
                     "edited_manually": 1},
                    origin="batch", batch_id=bid,
                )
                changed += 1
            elif action == "approve_suggestion":
                sug = row.get("suggestion")
                if not sug:
                    ignored += 1
                    continue
                if row["status"] == "approved" and not overwrite_approved:
                    skipped += 1
                    continue
                self.update(
                    rel, {"approved_description": sug, "status": "approved"},
                    origin="batch", batch_id=bid,
                )
                changed += 1
            elif action == "mark_review":
                self.update(rel, {"status": "review"}, origin="batch", batch_id=bid)
                changed += 1
            elif action == "hide":
                self.update(rel, {"visible": 0}, origin="batch", batch_id=bid)
                changed += 1
            elif action == "show":
                self.update(rel, {"visible": 1}, origin="batch", batch_id=bid)
                changed += 1
        return {"changed": changed, "skipped": skipped, "ignored": ignored,
                "requested": len(rel_paths)}

    def batch_preview(self, rel_paths: list[str], overwrite_approved: bool) -> dict[str, Any]:
        approved = pending = 0
        for rel in rel_paths:
            row = self._repo.get(rel)
            if not row:
                continue
            if row["status"] == "approved":
                approved += 1
            else:
                pending += 1
        will_change = len(rel_paths) if overwrite_approved else pending
        return {
            "selected": len(rel_paths),
            "already_approved": approved,
            "pending": pending,
            "will_change": will_change,
            "ignored_protected": 0 if overwrite_approved else approved,
        }

    def select_all(self, filters, search, year) -> list[str]:
        return self._repo.rel_paths_for_filter(filters, search, year)

    # -- integration helpers (slideshow / overlay) ------------------------

    def is_hidden(self, abs_path: str) -> bool:
        root = self.pic_dir()
        try:
            rel = os.path.relpath(abs_path, root)
        except ValueError:
            return False
        row = self._repo.get(rel)
        return bool(row and row["visible"] == 0)

    def description_for(self, abs_path: str) -> str | None:
        root = self.pic_dir()
        try:
            rel = os.path.relpath(abs_path, root)
        except ValueError:
            return None
        row = self._repo.get(rel)
        if not row:
            return None
        if row["approved_description"]:
            return row["approved_description"]
        if self._config.get_app_config_bool(CFG_SHOW_UNAPPROVED, False):
            return row["suggestion"] or None
        return None

    def thumbnail_abspath(self, rel_path: str) -> str:
        return os.path.join(self.pic_dir(), rel_path)

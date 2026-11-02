"""
PhotoOptimizerService for in-place optimization of the local photo library.

Unlike :class:`ImageProcessingService`, which writes resized *copies* into a
render cache, this service rewrites the original files under ``model.pic_dir``
in place so the on-disk library stays small and portable. It preserves each
file's name and extension, honours EXIF orientation, never upscales, crops or
stretches, and replaces originals atomically (temp file on the same filesystem
+ ``os.replace``) only after the rewritten file has been validated. A failed
rewrite leaves the original untouched and removes the temporary file.

The operation is idempotent: files already within the target bounds are skipped,
so repeated runs (e.g. after an rclone sync pulls new photos) only touch files
that still need shrinking.

Runs happen on a single background thread; status is exposed for the web panel
(analysed / resized / already-ok counts, bytes saved, last run, errors).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from picframe.core.repositories.interfaces import IConfigRepository

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Configuration keys (persisted in config.db3 via the config repository).
CFG_ENABLED = "optimizer.enabled"
CFG_MAX_WIDTH = "optimizer.max_width"
CFG_MAX_HEIGHT = "optimizer.max_height"
CFG_QUALITY = "optimizer.quality"
CFG_PRESERVE_ASPECT = "optimizer.preserve_aspect"
CFG_PIC_DIR = "model.pic_dir"

DEFAULT_MAX_WIDTH = 1920
DEFAULT_MAX_HEIGHT = 1080
DEFAULT_QUALITY = 90
DEFAULT_PRESERVE_ASPECT = True

# Keep the per-file detail list bounded so status payloads stay small.
_MAX_DETAILS = 200


@dataclass
class OptimizerRunResult:
    """Outcome of a single scan/apply run."""

    mode: str = "scan"
    analyzed: int = 0
    resized: int = 0
    already_ok: int = 0
    skipped_unsupported: int = 0
    errors: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    bytes_saved: int = 0
    duration_s: float = 0.0
    details: list[dict[str, Any]] = field(default_factory=list)
    error_list: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "analyzed": self.analyzed,
            "resized": self.resized,
            "already_ok": self.already_ok,
            "skipped_unsupported": self.skipped_unsupported,
            "errors": self.errors,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "bytes_saved": self.bytes_saved,
            "duration_s": round(self.duration_s, 2),
            "ok": self.errors == 0,
            "details": self.details,
            "error_list": self.error_list,
        }


def target_size(
    width: int, height: int, max_w: int, max_h: int, preserve_aspect: bool = True
) -> tuple[int, int]:
    """Target dimensions for the optimizer. Never upscales.

    With ``preserve_aspect`` (the default) the image is scaled down uniformly to
    fit within ``(max_w, max_h)``, so it is never stretched or cropped. Without
    it, each axis is capped independently at its own maximum, which can change
    the aspect ratio -- the caller surfaces that as a possible distortion in the
    web panel. Either way an image already within bounds is left untouched.
    """
    if preserve_aspect:
        scale = min(max_w / width, max_h / height, 1.0)
        return (max(1, round(width * scale)), max(1, round(height * scale)))
    return (min(width, max_w), min(height, max_h))


class PhotoOptimizerService:
    """Resize the originals under ``model.pic_dir`` in place, safely and idempotently."""

    def __init__(self, config_repository: IConfigRepository) -> None:
        self._config = config_repository
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._mode = "none"
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._progress_current = 0
        self._progress_total = 0
        self._progress_file = ""
        self._last_result: OptimizerRunResult | None = None

    # -- configuration -----------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Return the persisted optimizer configuration with defaults applied."""
        return {
            "enabled": self._config.get_app_config_bool(CFG_ENABLED, False),
            "max_width": self._as_int(self._config.get_app_config(CFG_MAX_WIDTH), DEFAULT_MAX_WIDTH),
            "max_height": self._as_int(
                self._config.get_app_config(CFG_MAX_HEIGHT), DEFAULT_MAX_HEIGHT
            ),
            "quality": self._as_int(self._config.get_app_config(CFG_QUALITY), DEFAULT_QUALITY),
            "preserve_aspect": self._config.get_app_config_bool(
                CFG_PRESERVE_ASPECT, DEFAULT_PRESERVE_ASPECT
            ),
            "pic_dir": str(self._config.get_app_config(CFG_PIC_DIR) or ""),
        }

    def set_config(
        self,
        enabled: bool | None = None,
        max_width: int | None = None,
        max_height: int | None = None,
        quality: int | None = None,
        preserve_aspect: bool | None = None,
    ) -> dict[str, Any]:
        """Persist optimizer settings. Only provided fields are updated."""
        if enabled is not None:
            self._config.set_app_config(CFG_ENABLED, bool(enabled))
        if max_width is not None:
            self._config.set_app_config(CFG_MAX_WIDTH, self._clamp(max_width, 320, 7680))
        if max_height is not None:
            self._config.set_app_config(CFG_MAX_HEIGHT, self._clamp(max_height, 240, 4320))
        if quality is not None:
            self._config.set_app_config(CFG_QUALITY, self._clamp(quality, 40, 100))
        if preserve_aspect is not None:
            self._config.set_app_config(CFG_PRESERVE_ASPECT, bool(preserve_aspect))
        return self.get_config()

    # -- status ------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of the current/last run for the web panel."""
        with self._lock:
            return {
                "running": self._running,
                "mode": self._mode,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "progress": {
                    "current": self._progress_current,
                    "total": self._progress_total,
                    "file": self._progress_file,
                },
                "last_result": self._last_result.as_dict() if self._last_result else None,
                "config": self.get_config(),
            }

    # -- run control -------------------------------------------------------

    def start_run(self, mode: str = "scan") -> bool:
        """Start a background run. Returns False if a run is already in progress.

        ``mode`` is ``"scan"`` (dry-run report), ``"apply"`` (rewrite in place) or
        ``"verify"`` (dry-run that re-reads every file to confirm integrity).
        """
        if mode not in ("scan", "apply", "verify"):
            raise ValueError(f"Unsupported optimizer mode: {mode}")
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._mode = mode
            self._started_at = time.time()
            self._finished_at = None
            self._progress_current = 0
            self._progress_total = 0
            self._progress_file = ""
            self._thread = threading.Thread(
                target=self._run, args=(mode,), name="PhotoOptimizer", daemon=True
            )
            self._thread.start()
        logger.info("Photo optimizer run started (mode=%s)", mode)
        return True

    def run_sync(self, mode: str = "apply") -> OptimizerRunResult:
        """Run optimization synchronously and return the result (used by schedulers)."""
        apply = mode == "apply"
        return self._optimize(apply=apply, mode=mode)

    # -- internals ---------------------------------------------------------

    def _run(self, mode: str) -> None:
        apply = mode == "apply"
        try:
            result = self._optimize(apply=apply, mode=mode)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Photo optimizer run failed: %s", exc)
            result = OptimizerRunResult(mode=mode, errors=1)
            result.error_list.append({"file": "", "error": str(exc)})
        with self._lock:
            self._running = False
            self._finished_at = time.time()
            self._last_result = result
        logger.info(
            "Photo optimizer run finished (mode=%s): analyzed=%d resized=%d already_ok=%d errors=%d",
            mode,
            result.analyzed,
            result.resized,
            result.already_ok,
            result.errors,
        )

    def _optimize(self, apply: bool, mode: str) -> OptimizerRunResult:
        cfg = self.get_config()
        root = cfg["pic_dir"]
        result = OptimizerRunResult(mode=mode)
        start = time.time()
        if not root or not os.path.isdir(root):
            result.errors += 1
            result.error_list.append({"file": "", "error": f"pic_dir not found: {root!r}"})
            result.duration_s = time.time() - start
            return result

        files = self._collect_files(root)
        with self._lock:
            self._progress_total = len(files)
        for index, path in enumerate(files, start=1):
            with self._lock:
                self._progress_current = index
                self._progress_file = os.path.basename(path)
            self._process_file(
                path,
                cfg["max_width"],
                cfg["max_height"],
                cfg["quality"],
                cfg["preserve_aspect"],
                apply,
                result,
            )
        result.duration_s = time.time() - start
        return result

    @staticmethod
    def _collect_files(root: str) -> list[str]:
        collected: list[str] = []
        for dirpath, _dirs, files in os.walk(root):
            for name in sorted(files):
                if name.startswith(".fp_opt_"):  # our own in-flight temp files
                    continue
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
                    collected.append(os.path.join(dirpath, name))
        return collected

    def _process_file(
        self,
        path: str,
        max_w: int,
        max_h: int,
        quality: int,
        preserve_aspect: bool,
        apply: bool,
        result: OptimizerRunResult,
    ) -> None:
        ext = os.path.splitext(path)[1].lower()
        result.analyzed += 1
        name = os.path.basename(path)
        try:
            size_before = os.path.getsize(path)
            # 1) Validate the source is a readable, uncorrupted image.
            with Image.open(path) as probe:
                probe.verify()
            with Image.open(path) as src:
                image = ImageOps.exif_transpose(src)
                # Preserve relevant metadata across the rewrite. exif_transpose
                # already normalised the Orientation tag on the returned image's
                # EXIF, so re-embedding it will not double-rotate the pixels.
                exif = image.info.get("exif")
                icc = image.info.get("icc_profile") or src.info.get("icc_profile")
                orig_w, orig_h = image.size
                new_w, new_h = target_size(orig_w, orig_h, max_w, max_h, preserve_aspect)
                if (new_w, new_h) == (orig_w, orig_h):
                    result.already_ok += 1
                    self._append_detail(
                        result, {"file": name, "action": "already_ok", "dims": f"{orig_w}x{orig_h}"}
                    )
                    return

                resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
                directory = os.path.dirname(path) or "."
                handle, tmp = tempfile.mkstemp(prefix=".fp_opt_", suffix=ext, dir=directory)
                os.close(handle)
                try:
                    self._save(resized, tmp, ext, quality, exif, icc)
                    # 2) Validate the generated file before touching the original.
                    with Image.open(tmp) as check:
                        check.verify()
                    with Image.open(tmp) as check2:
                        if check2.size != (new_w, new_h):
                            raise ValueError(
                                f"temp dims {check2.size} != expected {(new_w, new_h)}"
                            )
                    size_after = os.path.getsize(tmp)
                    if apply:
                        # 3) Atomic, name-preserving replacement.
                        os.replace(tmp, path)
                        tmp = None
                    result.resized += 1
                    result.bytes_before += size_before
                    result.bytes_after += size_after
                    result.bytes_saved += max(0, size_before - size_after)
                    self._append_detail(
                        result,
                        {
                            "file": name,
                            "action": "resize",
                            "from": f"{orig_w}x{orig_h}",
                            "to": f"{new_w}x{new_h}",
                            "bytes_before": size_before,
                            "bytes_after": size_after,
                        },
                    )
                finally:
                    if tmp and os.path.exists(tmp):
                        os.remove(tmp)
        except Exception as exc:
            result.errors += 1
            result.error_list.append({"file": name, "error": str(exc)})
            logger.warning("Photo optimizer could not process %s: %s", name, exc)

    @staticmethod
    def _save(
        image: Image.Image,
        dest: str,
        ext: str,
        quality: int,
        exif: bytes | None = None,
        icc: bytes | None = None,
    ) -> None:
        # Only pass metadata kwargs when present: Pillow rejects ``exif=None`` on
        # some versions and an empty ICC profile is meaningless.
        save_kwargs: dict[str, Any] = {}
        if exif:
            save_kwargs["exif"] = exif
        if icc:
            save_kwargs["icc_profile"] = icc
        if ext in (".jpg", ".jpeg"):
            out = image if image.mode in ("RGB", "L") else image.convert("RGB")
            out.save(
                dest,
                format="JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
                **save_kwargs,
            )
        else:  # .png
            image.save(dest, format="PNG", optimize=True, **save_kwargs)

    @staticmethod
    def _append_detail(result: OptimizerRunResult, detail: dict[str, Any]) -> None:
        if len(result.details) < _MAX_DETAILS:
            result.details.append(detail)

    @staticmethod
    def _as_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(value: Any, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(value)))
        except (TypeError, ValueError):
            return low

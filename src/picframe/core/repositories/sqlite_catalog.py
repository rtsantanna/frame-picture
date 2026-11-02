"""
Durable catalog repository for the "Catalogo de Memorias" feature.

This owns ``catalog.db3`` and is deliberately SEPARATE from ``media_cache.db3``:
the media cache is ephemeral (it can be rebuilt/purged), while the catalog holds
*human decisions* — approved descriptions, approval status and slideshow
visibility — that must survive restarts, container recreation AND a media-cache
rebuild (Missao Mestre item 13). Rows are keyed by the media's path relative to
``model.pic_dir`` (a stable identifier that survives in-place optimization,
which preserves names), never by a content hash of the optimized file.

Scan writes only refresh *extracted* metadata; they never overwrite the
approval columns of an existing row, so re-scanning after a sync is safe.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

from picframe.core.repositories.migrations import Migration, MigrationManager

# Columns refreshed by a scan (extracted metadata). Approval columns
# (approved_description, status, visible, edited_manually) are intentionally
# excluded so a rescan never clobbers a human decision.
_SCAN_COLUMNS = (
    "filename",
    "media_type",
    "mime",
    "filetype",
    "capture_date",
    "date_source",
    "tz_offset",
    "gps_lat",
    "gps_lon",
    "gps_alt",
    "make",
    "model",
    "orientation",
    "width",
    "height",
    "duration_s",
    "file_size",
    "file_mtime",
)

CATALOG_MIGRATIONS = [
    Migration(
        version=1,
        up_script="""
        CREATE TABLE IF NOT EXISTS catalog (
            rel_path              TEXT PRIMARY KEY,
            filename              TEXT NOT NULL,
            media_type            TEXT,
            mime                  TEXT,
            filetype              TEXT,
            capture_date          TEXT,
            date_source           TEXT,
            tz_offset             TEXT,
            gps_lat               REAL,
            gps_lon               REAL,
            gps_alt               REAL,
            make                  TEXT,
            model                 TEXT,
            orientation           TEXT,
            width                 INTEGER,
            height                INTEGER,
            duration_s            REAL,
            suggestion            TEXT,
            suggestion_source     TEXT,
            suggestion_confidence TEXT,
            approved_description  TEXT,
            status                TEXT NOT NULL DEFAULT 'pending',
            visible               INTEGER NOT NULL DEFAULT 1,
            edited_manually       INTEGER NOT NULL DEFAULT 0,
            file_size             INTEGER,
            file_mtime            REAL,
            first_seen            REAL,
            updated_at            REAL
        );
        CREATE INDEX IF NOT EXISTS idx_catalog_status ON catalog(status);
        CREATE INDEX IF NOT EXISTS idx_catalog_visible ON catalog(visible);
        CREATE INDEX IF NOT EXISTS idx_catalog_type ON catalog(media_type);
        """,
    ),
    Migration(
        version=2,
        up_script="""
        CREATE TABLE IF NOT EXISTS geocode_cache (
            key    TEXT PRIMARY KEY,
            place  TEXT,
            ts     REAL
        );
        """,
    ),
]

# Named filters -> SQL WHERE fragment (no user input interpolated).
_FILTERS: dict[str, str] = {
    "all": "1=1",
    "pending": "status = 'pending'",
    "approved": "status = 'approved'",
    "review": "status = 'review'",
    "auto_location": "suggestion_source IN ('gps','filename','group') AND status != 'approved'",
    "with_suggestion": "suggestion IS NOT NULL AND suggestion != ''",
    "no_info": "(suggestion IS NULL OR suggestion = '') AND (approved_description IS NULL OR approved_description = '')",
    "hidden": "visible = 0",
    "visible": "visible = 1",
    "with_gps": "gps_lat IS NOT NULL AND gps_lon IS NOT NULL",
    "no_gps": "gps_lat IS NULL OR gps_lon IS NULL",
    "photos": "media_type = 'photo'",
    "videos": "media_type = 'video'",
    "with_date": "capture_date IS NOT NULL AND capture_date != ''",
    "no_date": "capture_date IS NULL OR capture_date = ''",
    "edited": "edited_manually = 1",
}

_SORTS: dict[str, str] = {
    "date_desc": "capture_date DESC",
    "date_asc": "capture_date ASC",
    "name_asc": "filename COLLATE NOCASE ASC",
    "name_desc": "filename COLLATE NOCASE DESC",
    "status": "status ASC, filename COLLATE NOCASE ASC",
}


class SQLiteCatalogRepository:
    """SQLite-backed durable store for catalog (human-curated) media state."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            MigrationManager(self._conn, CATALOG_MIGRATIONS).migrate()

    # -- scan / upsert -----------------------------------------------------

    def upsert_scanned(self, rel_path: str, meta: dict[str, Any]) -> None:
        """Insert a new row or refresh only the extracted-metadata columns of an
        existing one. Approval columns are never touched here."""
        now = time.time()
        cols = ["rel_path", *_SCAN_COLUMNS, "first_seen", "updated_at"]
        values = [rel_path] + [meta.get(c) for c in _SCAN_COLUMNS] + [now, now]
        placeholders = ",".join("?" for _ in cols)
        update_set = ",".join(f"{c}=excluded.{c}" for c in _SCAN_COLUMNS)
        sql = (
            f"INSERT INTO catalog ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(rel_path) DO UPDATE SET {update_set}, updated_at=excluded.updated_at"
        )
        with self._lock:
            self._conn.execute(sql, values)

    def set_suggestion(
        self, rel_path: str, suggestion: str, source: str, confidence: str
    ) -> None:
        """Set the auto-suggestion. Only applied when the row is not approved,
        so an approved description is never shadowed by a fresh suggestion."""
        with self._lock:
            self._conn.execute(
                "UPDATE catalog SET suggestion=?, suggestion_source=?, suggestion_confidence=? "
                "WHERE rel_path=? AND status != 'approved'",
                (suggestion, source, confidence, rel_path),
            )

    def known_rel_paths(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT rel_path FROM catalog").fetchall()
        return {r["rel_path"] for r in rows}

    def delete(self, rel_path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM catalog WHERE rel_path=?", (rel_path,))

    # -- reads -------------------------------------------------------------

    def get(self, rel_path: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM catalog WHERE rel_path=?", (rel_path,)
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        filters: list[str] | None = None,
        search: str | None = None,
        year: int | None = None,
        sort: str = "date_desc",
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (rows, total). ``filters`` are ANDed named filters."""
        where: list[str] = []
        params: list[Any] = []
        for f in filters or ["all"]:
            where.append("(" + _FILTERS.get(f, "1=1") + ")")
        if search:
            where.append(
                "(filename LIKE ? OR suggestion LIKE ? OR approved_description LIKE ?)"
            )
            like = f"%{search}%"
            params += [like, like, like]
        if year is not None:
            where.append("substr(capture_date,1,4) = ?")
            params.append(str(year))
        where_sql = " AND ".join(where) if where else "1=1"
        order = _SORTS.get(sort, _SORTS["date_desc"])
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS n FROM catalog WHERE {where_sql}", params
            ).fetchone()["n"]
            rows = self._conn.execute(
                f"SELECT * FROM catalog WHERE {where_sql} ORDER BY {order} LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return [dict(r) for r in rows], int(total)

    def rel_paths_for_filter(
        self, filters: list[str] | None, search: str | None, year: int | None
    ) -> list[str]:
        """All rel_paths matching a filter set (used by 'select all results')."""
        rows, _ = self.list(filters, search, year, sort="name_asc", limit=1_000_000, offset=0)
        return [r["rel_path"] for r in rows]

    def stats(self) -> dict[str, int]:
        q = (
            "SELECT "
            "COUNT(*) AS total, "
            "SUM(media_type='photo') AS photos, "
            "SUM(media_type='video') AS videos, "
            "SUM(status='approved') AS approved, "
            "SUM(status='pending') AS pending, "
            "SUM(status='review') AS review, "
            "SUM(gps_lat IS NOT NULL AND gps_lon IS NOT NULL) AS with_gps, "
            "SUM(gps_lat IS NULL OR gps_lon IS NULL) AS no_gps, "
            "SUM(suggestion IS NOT NULL AND suggestion != '') AS with_suggestion, "
            "SUM((suggestion IS NULL OR suggestion='') AND (approved_description IS NULL OR approved_description='')) AS no_info, "
            "SUM(visible=0) AS hidden "
            "FROM catalog"
        )
        with self._lock:
            row = self._conn.execute(q).fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}

    # -- writes (human decisions) -----------------------------------------

    def update_fields(self, rel_path: str, fields: dict[str, Any]) -> bool:
        allowed = {
            "approved_description",
            "status",
            "visible",
            "edited_manually",
            "suggestion",
            "suggestion_source",
            "suggestion_confidence",
        }
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return False
        sets["updated_at"] = time.time()
        assignments = ",".join(f"{k}=?" for k in sets)
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE catalog SET {assignments} WHERE rel_path=?",
                list(sets.values()) + [rel_path],
            )
        return cur.rowcount > 0

    def visible_map(self) -> dict[str, int]:
        """rel_path -> visible flag, for slideshow filtering."""
        with self._lock:
            rows = self._conn.execute("SELECT rel_path, visible FROM catalog").fetchall()
        return {r["rel_path"]: int(r["visible"]) for r in rows}

    def approved_description(self, rel_path: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT approved_description FROM catalog WHERE rel_path=?", (rel_path,)
            ).fetchone()
        return row["approved_description"] if row else None

    # -- geocode cache -----------------------------------------------------

    @staticmethod
    def _geo_key(lat: float, lon: float) -> str:
        # ~0.001 deg (~100 m) bucket so nearby photos share a lookup.
        return f"{round(float(lat), 3)},{round(float(lon), 3)}"

    def get_geocode(self, lat: float, lon: float) -> str | None:
        """Return the cached place ("" = looked up, no result) or None if never
        looked up."""
        with self._lock:
            row = self._conn.execute(
                "SELECT place FROM geocode_cache WHERE key=?", (self._geo_key(lat, lon),)
            ).fetchone()
        return row["place"] if row else None

    def set_geocode(self, lat: float, lon: float, place: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO geocode_cache (key, place, ts) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET place=excluded.place, ts=excluded.ts",
                (self._geo_key(lat, lon), place, time.time()),
            )

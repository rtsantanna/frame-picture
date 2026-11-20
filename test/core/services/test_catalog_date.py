"""Corrected capture date in the catalog (WhatsApp copies and similar)."""

from typing import Any

import pytest

from picframe.core.repositories.sqlite_catalog import SQLiteCatalogRepository
from picframe.core.services.catalog_service import (
    CatalogService,
    normalize_catalog_date,
    parse_catalog_date,
    suggest_from_filename,
)


@pytest.mark.parametrize("name", ["IMG-20260620-WA0004.jpeg", "VID-20190512-WA0001.mp4"])
def test_whatsapp_names_give_no_place_suggestion(name: str) -> None:
    assert suggest_from_filename(name) == (None, "none", "low")


class FakeConfig:
    def __init__(self, pic_dir: str) -> None:
        self.values: dict[str, Any] = {"model.pic_dir": pic_dir}

    def get_app_config(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_app_config_bool(self, key: str, default: bool = False) -> bool:
        return bool(self.values.get(key, default))

    def set_app_config(self, key: str, value: Any) -> None:
        self.values[key] = value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2019-05-12", "2019:05:12 12:00:00"),
        ("2019:05:12 08:30:15", "2019:05:12 08:30:15"),
        ("2019-05-12T08:30", "2019:05:12 08:30:00"),
        ("2019:05:12 08:30:15+02:00", "2019:05:12 08:30:15"),
        ("2019-02-30", ""),
        ("hoje", ""),
        ("", ""),
    ],
)
def test_normalize_catalog_date(raw: str, expected: str) -> None:
    assert normalize_catalog_date(raw) == expected


def test_override_wins_and_survives_rescan(tmp_path: Any) -> None:
    repo = SQLiteCatalogRepository(str(tmp_path / "catalog.db3"))
    svc = CatalogService(repo, FakeConfig(str(tmp_path)))
    repo.upsert_scanned("IMG-20190512-WA0003.jpg", {"filename": "IMG-20190512-WA0003.jpg",
                                                    "media_type": "photo",
                                                    "capture_date": "2025:11:01 10:00:00"})
    abs_path = str(tmp_path / "IMG-20190512-WA0003.jpg")

    svc.set_date("IMG-20190512-WA0003.jpg", "2019-05-12")
    assert svc.date_for(abs_path) == parse_catalog_date("2019:05:12 12:00:00")

    # A rescan refreshes capture_date but never the human correction.
    repo.upsert_scanned("IMG-20190512-WA0003.jpg", {"filename": "IMG-20190512-WA0003.jpg",
                                                    "media_type": "photo",
                                                    "capture_date": "2025:11:02 10:00:00"})
    row = repo.get("IMG-20190512-WA0003.jpg")
    assert row["date_override"] == "2019:05:12 12:00:00"
    rows, total = repo.list(filters=["date_edited"], year=2019)
    assert total == 1 and rows[0]["rel_path"] == "IMG-20190512-WA0003.jpg"
    events = [e["event"] for e in repo.get_history("IMG-20190512-WA0003.jpg")]
    assert "date_changed" in events

    svc.set_date("IMG-20190512-WA0003.jpg", "")
    assert svc.date_for(abs_path) == parse_catalog_date("2025:11:02 10:00:00")
    assert "date_reset" in [e["event"] for e in repo.get_history("IMG-20190512-WA0003.jpg")]

    with pytest.raises(ValueError):
        svc.set_date("IMG-20190512-WA0003.jpg", "31/31/2019")

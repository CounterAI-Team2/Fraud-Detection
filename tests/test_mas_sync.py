from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import mas_sanctions_sync as mss

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_index_catalog_extracts_rows():
    rows = mss.parse_index_catalog(_read("mas_index.html"))

    assert len(rows) == 2
    keys = {row["key"]: row for row in rows}
    assert "iran-list" in keys
    iran = keys["iran-list"]
    assert iran["category"] == "Iran"
    assert iran["last_updated"] == "04 Apr 2026"
    assert iran["list_url"].startswith("https://www.mas.gov.sg/")


def test_find_alphabetical_html_prefers_alphabetical_anchor():
    url = mss.find_alphabetical_html(
        _read("mas_list_page.html"),
        base_url="https://www.mas.gov.sg/regulation/iran-list",
    )
    assert url is not None
    assert url.endswith("/files/iran-designated-list-alphabetical.html")


def test_parse_names_from_html_returns_normalized_names():
    names = mss.parse_names_from_html(_read("mas_alphabetical_list.html"))
    upper = set(names)

    assert "ABBAS RASHIDI" in upper
    assert "MOHAMMAD REZA ZAHEDI" in upper
    # Header/footer text should not appear as a name.
    assert not any("PAGE" in n for n in upper)


def test_maintenance_page_detection():
    maintenance = "<!doctype html><html><head><title>Maintenance</title></head><body>busy</body></html>"
    assert mss._looks_like_maintenance(maintenance)
    assert not mss._looks_like_maintenance("<html><body><h1>hello</h1></body></html>")


def test_sync_catalog_diff_skips_unchanged_lists(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "LAST_SYNC_PATH", tmp_path / "last_sync.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names.txt")

    index_html = _read("mas_index.html")
    list_html = _read("mas_list_page.html")
    alpha_html = _read("mas_alphabetical_list.html")

    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        if "lists-of-designated-individuals" in url:
            return index_html
        if url.endswith("alphabetical.html"):
            return alpha_html
        return list_html

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    first = mss.sync_mas_sanctions()
    assert first.status == "ok"
    assert set(first.lists_updated) == {"iran-list", "counter-terrorism-list"}
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert catalog["lists"]["iran-list"]["last_updated"] == "04 Apr 2026"

    fetched.clear()
    second = mss.sync_mas_sanctions()
    assert second.status == "skipped"
    assert second.lists_updated == []
    # Index is always fetched, but no list pages should be re-downloaded.
    assert len(fetched) == 1


def test_sync_picks_up_changed_last_updated(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "LAST_SYNC_PATH", tmp_path / "last_sync.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names.txt")

    base_index = _read("mas_index.html")
    bumped_index = base_index.replace("04 Apr 2026", "10 May 2026")

    state = {"index": base_index}

    def fake_fetch(url: str) -> str:
        if "lists-of-designated-individuals" in url:
            return state["index"]
        if url.endswith("alphabetical.html"):
            return _read("mas_alphabetical_list.html")
        return _read("mas_list_page.html")

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    mss.sync_mas_sanctions()
    state["index"] = bumped_index
    result = mss.sync_mas_sanctions()

    assert result.status == "ok"
    assert "iran-list" in result.lists_updated
    # Counter-terrorism row was unchanged, so it should not be re-downloaded.
    assert "counter-terrorism-list" not in result.lists_updated


@pytest.fixture(autouse=True)
def _reset_screen_cache():
    mss._clear_screening_cache()
    yield
    mss._clear_screening_cache()

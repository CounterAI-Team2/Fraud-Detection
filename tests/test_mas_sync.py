from __future__ import annotations

import json
from pathlib import Path

import pytest

from utils import mas_sanctions_sync as mss

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_index_catalog_extracts_un_list_links():
    rows = mss.parse_index_catalog(_read("mas_index_un.html"))

    assert len(rows) == 4
    keys = {row["key"]: row for row in rows}
    assert "un-1718-list" in keys
    assert "un-1737-list" in keys
    assert "isil-da-esh-and-al-qaida-list" in keys
    assert "un-1988-taliban-list" in keys

    iran = keys["un-1737-list"]
    assert iran["category"] == "Iran"
    assert iran["last_updated"] == "27 Sep 2025"
    assert iran["list_url"] == "https://main.un.org/securitycouncil/en/sanctions/1737/materials"

    isil = keys["isil-da-esh-and-al-qaida-list"]
    assert isil["category"] == "Counter-Terrorism"
    assert isil["last_updated"] == "21 May 2026"
    assert "1267/aq_sanctions_list" in isil["list_url"]


def test_is_un_sanctions_list_url_skips_tsfa_first_schedule():
    assert mss.is_un_sanctions_list_url(
        "https://www.un.org/securitycouncil/sanctions/1737/materials"
    )
    assert not mss.is_un_sanctions_list_url(
        "https://sso.agc.gov.sg/Act/TSFA2002?ProvIds=Sc1-#Sc1-"
    )


def test_fetch_all_list_landing_pages_opens_every_discovered_link(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "LANDINGS_DIR", tmp_path / "landings")
    refs = mss.discover_sanctions_lists(_read("mas_index_un.html"))
    fetched_urls: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched_urls.append(url)
        return f"<html><body>Landing for {url}</body></html>"

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    landings = mss.fetch_all_list_landing_pages(refs)
    assert len(landings) == 4
    assert len(fetched_urls) == 4
    assert all(landing.status == "ok" for landing in landings)
    assert all(landing.landing_path for landing in landings)
    assert {landing.ref.list_url for landing in landings} == set(fetched_urls)


def test_find_alphabetical_html_download_prefers_alphabetical_section_html_link():
    url = mss.find_alphabetical_html_download(
        _read("un_landing_1267.html"),
        base_url="https://www.un.org/securitycouncil/en/sanctions/1267/aq_sanctions_list",
    )
    assert url == "https://scsanctions.un.org/en/?keywords=al-qaida"


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


def test_parse_un_sc_export_combines_numbered_name_parts_and_entities():
    names = mss.parse_names_from_html(_read("un_sc_export_sample.html"))

    assert "ABD AL-RAHMAN OULD MUHAMMAD AL-HUSAYN OULD MUHAMMAD SALIM" in names
    assert "ABD AL-BASET AZZOUZ" in names
    assert "RAJAH SOLAIMAN MOVEMENT" in names
    assert not any("RAJAH SOLAIMAN ISLAMIC MOVEMENT" in n for n in names)


def test_parse_names_from_file_writes_matching_txt(tmp_path):
    html_path = tmp_path / "al-qaida_all_name_legacy.html"
    html_path.write_text(_read("un_sc_export_sample.html"), encoding="utf-8")

    names = mss.parse_names_from_file(html_path)

    txt_path = tmp_path / "al-qaida_all_name_legacy.txt"
    assert txt_path.exists()
    assert txt_path.read_text(encoding="utf-8").splitlines() == names


def test_parse_names_from_upload_reads_plain_text_and_csv():
    txt_names = mss.parse_names_from_upload(
        "Aiman Muhammed Rabi Al-Zawahiri\nAgus Dwikarna\n",
        filename="demo.txt",
    )
    assert txt_names == ["AIMAN MUHAMMED RABI AL-ZAWAHIRI", "AGUS DWIKARNA"]

    csv_names = mss.parse_names_from_upload(
        "full_name,nationality\nMohammad Reza Zahedi,Iran\nAbbas Rashidi,Iran\n",
        filename="iran.csv",
    )
    assert "MOHAMMAD REZA ZAHEDI" in csv_names
    assert "ABBAS RASHIDI" in csv_names


def test_import_uploaded_list_rescreens_kyc(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "LANDINGS_DIR", tmp_path / "lists" / "landings")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names_consolidated.txt")

    rescreen_calls: list[dict] = []

    def fake_rescreen():
        payload = {"exact": 2, "fuzzy": 1, "skipped": 0, "fuzzy_queue": [{"customer_id": "1"}]}
        rescreen_calls.append(payload)
        return payload

    monkeypatch.setattr("utils.kyc_store.force_rescreen_kyc_sanctions", fake_rescreen)

    result = mss.import_uploaded_list(
        "Aiman Muhammed Rabi Al-Zawahiri\nAgus Dwikarna\n",
        key="demo-list",
        filename="demo.txt",
    )

    assert result["name_count"] == 2
    assert (tmp_path / "lists" / "demo-list.txt").exists()
    assert rescreen_calls
    assert result["rescreen"]["exact"] == 2


def test_rebuild_names_from_downloaded_html_builds_consolidated(tmp_path, monkeypatch):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names_consolidated.txt")

    html_path = tmp_path / "lists" / "al-qaida_all_name_legacy.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text(_read("un_sc_export_sample.html"), encoding="utf-8")

    result = mss.rebuild_names_from_downloaded_html()

    assert result["lists_parsed"] == 1
    assert result["name_count"] == 3
    assert (tmp_path / "lists" / "al-qaida_all_name_legacy.txt").exists()
    consolidated = (tmp_path / "names_consolidated.txt").read_text(encoding="utf-8")
    assert "RAJAH SOLAIMAN MOVEMENT" in consolidated


def test_maintenance_page_detection():
    maintenance = "<!doctype html><html><head><title>Maintenance</title></head><body>busy</body></html>"
    assert mss._looks_like_maintenance(maintenance)
    assert not mss._looks_like_maintenance("<html><body><h1>hello</h1></body></html>")


def test_fetch_alphabetical_list_html_downloads_export(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path)
    ref = mss.discover_sanctions_lists(_read("mas_index_un.html"))[2]
    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        return "<html><body><h1>Sanctions list export</h1></body></html>"

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    result = mss.fetch_alphabetical_list_html(ref, _read("un_landing_1267.html"))
    assert result.status == "ok"
    assert result.download_url == "https://scsanctions.un.org/en/?keywords=al-qaida"
    assert fetched == ["https://scsanctions.un.org/en/?keywords=al-qaida"]
    assert Path(result.html_path).exists()
    assert "Sanctions list export" in Path(result.html_path).read_text(encoding="utf-8")


def test_sync_fetches_un_landing_pages(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "LANDINGS_DIR", tmp_path / "lists" / "landings")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "LAST_SYNC_PATH", tmp_path / "last_sync.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names.txt")

    index_html = _read("mas_index_un.html")
    fetched: list[str] = []

    un_landing = _read("un_landing_1267.html")

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        if "lists-of-designated-individuals" in url:
            return index_html
        if "scsanctions.un.org" in url:
            return "<html><body><h1>Exported list HTML</h1></body></html>"
        return un_landing

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    first = mss.sync_mas_sanctions()
    assert first.status in {"ok", "partial"}
    assert first.lists_discovered == 4
    assert first.landings_fetched == 4
    assert first.html_downloads == 4
    assert len(first.lists_updated) == 4
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    assert catalog["lists"]["un-1737-list"]["last_updated"] == "27 Sep 2025"
    assert catalog["lists"]["isil-da-esh-and-al-qaida-list"]["html_path"]
    assert Path(catalog["lists"]["isil-da-esh-and-al-qaida-list"]["html_path"]).exists()
    assert "scsanctions.un.org" in catalog["lists"]["isil-da-esh-and-al-qaida-list"]["download_url"]

    fetched.clear()
    second = mss.sync_mas_sanctions()
    assert second.status == "skipped"
    assert second.lists_updated == []
    assert len(fetched) == 1


def test_sync_picks_up_changed_last_updated(monkeypatch, tmp_path):
    monkeypatch.setattr(mss, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mss, "LISTS_DIR", tmp_path / "lists")
    monkeypatch.setattr(mss, "LANDINGS_DIR", tmp_path / "lists" / "landings")
    monkeypatch.setattr(mss, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(mss, "LAST_SYNC_PATH", tmp_path / "last_sync.json")
    monkeypatch.setattr(mss, "CONSOLIDATED_NAMES_PATH", tmp_path / "names.txt")

    base_index = _read("mas_index_un.html")
    bumped_index = base_index.replace("27 Sep 2025", "10 May 2026")

    state = {"index": base_index}

    un_landing = _read("un_landing_1267.html")

    def fake_fetch(url: str) -> str:
        if "lists-of-designated-individuals" in url:
            return state["index"]
        if "scsanctions.un.org" in url:
            return "<html><body><h1>Exported list HTML</h1></body></html>"
        return un_landing

    monkeypatch.setattr(mss, "_fetch", fake_fetch)

    mss.sync_mas_sanctions()
    state["index"] = bumped_index
    result = mss.sync_mas_sanctions()

    assert result.status in {"ok", "partial"}
    assert "un-1737-list" in result.lists_updated
    assert "un-1718-list" not in result.lists_updated


@pytest.fixture(autouse=True)
def _reset_screen_cache():
    mss._clear_screening_cache()
    yield
    mss._clear_screening_cache()

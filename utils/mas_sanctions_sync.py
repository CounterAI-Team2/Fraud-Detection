"""
MAS sanctions list sync.

This module polls the MAS Targeted Financial Sanctions index, downloads any
list whose Last Updated has changed (or that is not yet catalogued), parses
the alphabetical HTML list for each, and writes a consolidated names file
used by KYC name screening. The full implementation lives below; the
``screen_name`` helper is what the rest of the app calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable

MAS_INDEX_URL = (
    "https://www.mas.gov.sg/regulation/anti-money-laundering/"
    "targeted-financial-sanctions/lists-of-designated-individuals-and-entities"
)

DATA_DIR = Path("data/mas_sanctions")
LISTS_DIR = DATA_DIR / "lists"
CATALOG_PATH = DATA_DIR / "catalog.json"
LAST_SYNC_PATH = DATA_DIR / "last_sync.json"
CONSOLIDATED_NAMES_PATH = DATA_DIR / "names_consolidated.txt"

# How long a single HTTP request is allowed to block the app launch.
REQUEST_TIMEOUT_SECONDS = 15
# MAS's CDN serves a maintenance template to short / non-browser UAs, so we
# present a current Chrome-on-Windows UA. This is benign scraping of a public
# regulatory page.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
}


@dataclass
class SyncResult:
    status: str  # "ok", "partial", "skipped", "failed"
    lists_updated: list[str]
    name_count: int
    error: str | None = None
    fetched_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "lists_updated": self.lists_updated,
            "name_count": self.name_count,
            "error": self.error,
            "fetched_at": self.fetched_at or _utc_now_iso(),
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LISTS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "list"


def _read_catalog() -> dict:
    if not CATALOG_PATH.exists():
        return {"lists": {}}
    try:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"lists": {}}


def _write_catalog(data: dict) -> None:
    _ensure_dirs()
    CATALOG_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_last_sync(result: SyncResult) -> None:
    _ensure_dirs()
    LAST_SYNC_PATH.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")


def get_last_sync() -> dict | None:
    if not LAST_SYNC_PATH.exists():
        return None
    try:
        return json.loads(LAST_SYNC_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# --- HTTP helpers ----------------------------------------------------------

def _fetch(url: str) -> str:
    import requests  # local import keeps the cold path light when offline

    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS, headers=DEFAULT_HEADERS)
    response.raise_for_status()
    return response.text


# --- HTML parsers ----------------------------------------------------------

def _looks_like_maintenance(html: str) -> bool:
    snippet = html[:4000].lower()
    if "<title>maintenance</title>" in snippet:
        return True
    if "this service is currently unavailable" in html.lower():
        return True
    return False


_HEADER_LABELS = {
    "category",
    "revoked regulations/legislation",
    "date of revocation",
    "regulations/legislation",
    "list",
    "last updated",
}


def parse_index_catalog(html: str) -> list[dict[str, str]]:
    """Extract list entries from the MAS index page.

    The MAS table is laid out as ``Category | Regulations | List | Last Updated``;
    we pull the anchor from the **List** column (col index 2) so we follow links
    to the UN/MAS sanctions list page, not to the underlying Singapore regulation.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue
            # Skip header rows (either <th> or repeated text).
            first_text = cells[0].get_text(strip=True).lower()
            if any(cell.name == "th" for cell in cells) or first_text in _HEADER_LABELS:
                continue

            list_cell = cells[2]
            anchor = list_cell.find("a", href=True)
            if not anchor:
                continue

            href = anchor["href"].strip()
            if href.startswith("/"):
                href = "https://www.mas.gov.sg" + href

            label = anchor.get_text(" ", strip=True) or list_cell.get_text(" ", strip=True)
            category = cells[0].get_text(" ", strip=True)
            last_updated = cells[3].get_text(" ", strip=True)
            key = _slugify(label) or _slugify(category)
            if not key or not href:
                continue
            rows.append(
                {
                    "key": key,
                    "category": category,
                    "label": label,
                    "list_url": href,
                    "last_updated": last_updated,
                }
            )
    return rows


def find_alphabetical_html(list_page_html: str, base_url: str) -> str | None:
    """Find the anchor whose text mentions 'alphabetical' and href ends with .html."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(list_page_html, "html.parser")
    candidate = None
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        text = anchor.get_text(" ", strip=True).lower()
        if not href.lower().endswith(".html"):
            continue
        if "alphabetical" in text or "alphabetical" in href.lower():
            candidate = urljoin(base_url, href)
            break
    return candidate


def parse_names_from_html(html: str) -> list[str]:
    """Best-effort name extraction from a downloaded MAS list page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    names: list[str] = []
    seen: set[str] = set()

    # Prefer table rows and list items, fall back to <p>.
    candidates: Iterable = []
    for selector in ("table tr td", "ol li", "ul li", "p"):
        candidates = soup.select(selector)
        if candidates:
            for node in candidates:
                text = node.get_text(" ", strip=True)
                if not text or len(text) < 3:
                    continue
                # Skip obvious headers / footers.
                lowered = text.lower()
                if any(skip in lowered for skip in ("page ", "last updated", "regulation")):
                    continue
                normalized = _normalize_name(text)
                if normalized in seen:
                    continue
                seen.add(normalized)
                names.append(normalized)
            if names:
                break
    return names


# --- Sync orchestration ----------------------------------------------------

def _write_consolidated(names_by_list: dict[str, list[str]]) -> int:
    _ensure_dirs()
    seen: set[str] = set()
    for names in names_by_list.values():
        seen.update(names)
    CONSOLIDATED_NAMES_PATH.write_text("\n".join(sorted(seen)), encoding="utf-8")
    _clear_screening_cache()
    return len(seen)


def sync_mas_sanctions(force: bool = False) -> SyncResult:
    """Poll MAS, download changed lists, refresh the consolidated names file."""
    _ensure_dirs()
    catalog = _read_catalog()
    catalog_lists: dict[str, dict] = catalog.get("lists", {})

    try:
        index_html = _fetch(MAS_INDEX_URL)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        result = SyncResult(
            status="failed",
            lists_updated=[],
            name_count=_existing_name_count(),
            error=f"index fetch failed: {exc}",
        )
        _write_last_sync(result)
        return result

    if _looks_like_maintenance(index_html):
        result = SyncResult(
            status="failed",
            lists_updated=[],
            name_count=_existing_name_count(),
            error="MAS site is in maintenance mode; using cached sanctions data.",
        )
        _write_last_sync(result)
        return result

    rows = parse_index_catalog(index_html)
    if not rows:
        result = SyncResult(
            status="failed",
            lists_updated=[],
            name_count=_existing_name_count(),
            error="MAS index returned no list entries (layout change or empty response).",
        )
        _write_last_sync(result)
        return result

    lists_updated: list[str] = []
    needs_upload: list[str] = []
    errors: list[str] = []
    names_by_list: dict[str, list[str]] = {
        key: list(meta.get("names", []))
        for key, meta in catalog_lists.items()
    }

    for row in rows:
        key = row["key"]
        prior = catalog_lists.get(key, {})
        index_changed = (
            force
            or key not in catalog_lists
            or prior.get("last_updated") != row["last_updated"]
        )

        # Always refresh the catalog row so the UI shows the latest MAS metadata,
        # even when the actual list HTML cannot be auto-downloaded.
        entry: dict = {
            "category": row["category"],
            "label": row.get("label", ""),
            "list_url": row["list_url"],
            "last_updated": row["last_updated"],
            "alphabetical_url": prior.get("alphabetical_url", ""),
            "downloaded_at": prior.get("downloaded_at", ""),
            "name_count": prior.get("name_count", 0),
            "names": prior.get("names", []),
            "source": prior.get("source", ""),
            "needs_manual_upload": prior.get("needs_manual_upload", False),
        }

        if not index_changed and entry.get("names"):
            catalog_lists[key] = entry
            continue

        try:
            list_html = _fetch(row["list_url"])
            alpha_url = find_alphabetical_html(list_html, row["list_url"])
            if not alpha_url:
                raise RuntimeError("no alphabetical .html link found on list page")
            alpha_html = _fetch(alpha_url)
        except Exception as exc:  # noqa: BLE001 - per-list fault tolerance
            errors.append(f"{key}: {exc}")
            entry["needs_manual_upload"] = True
            entry["last_error"] = str(exc)
            catalog_lists[key] = entry
            needs_upload.append(key)
            continue

        out_path = LISTS_DIR / f"{key}.html"
        out_path.write_text(alpha_html, encoding="utf-8")
        names = parse_names_from_html(alpha_html)
        names_by_list[key] = names

        entry.update(
            {
                "alphabetical_url": alpha_url,
                "downloaded_at": _utc_now_iso(),
                "name_count": len(names),
                "names": names,
                "source": "auto",
                "needs_manual_upload": False,
                "last_error": "",
            }
        )
        catalog_lists[key] = entry
        lists_updated.append(key)

    catalog["lists"] = catalog_lists
    catalog["index_fetched_at"] = _utc_now_iso()
    _write_catalog(catalog)

    total = _write_consolidated(names_by_list)

    if lists_updated and not errors:
        status = "ok"
    elif lists_updated and errors:
        status = "partial"
    elif errors:
        status = "needs_upload" if all("needs_manual_upload" for _ in errors) else "failed"
    else:
        status = "skipped"

    error_msg = "; ".join(errors) if errors else None
    if needs_upload and not error_msg:
        error_msg = f"Manual upload required for: {', '.join(needs_upload)}"

    result = SyncResult(
        status=status,
        lists_updated=lists_updated,
        name_count=total,
        error=error_msg,
    )
    _write_last_sync(result)
    return result


def list_catalog_entries() -> list[dict]:
    """Return a UI-friendly view of the current catalog."""
    catalog = _read_catalog().get("lists", {})
    rows: list[dict] = []
    for key, meta in catalog.items():
        rows.append(
            {
                "key": key,
                "category": meta.get("category", ""),
                "label": meta.get("label", ""),
                "list_url": meta.get("list_url", ""),
                "last_updated": meta.get("last_updated", ""),
                "downloaded_at": meta.get("downloaded_at", ""),
                "name_count": meta.get("name_count", 0),
                "source": meta.get("source", ""),
                "needs_manual_upload": bool(meta.get("needs_manual_upload", False)),
                "last_error": meta.get("last_error", ""),
            }
        )
    return rows


def import_uploaded_list(
    html: str,
    key: str,
    label: str = "",
    category: str = "",
    last_updated: str = "",
) -> dict:
    """Persist a manually uploaded HTML list and rebuild the consolidated names file."""
    _ensure_dirs()
    key = _slugify(key) or _slugify(label) or "manual-list"

    out_path = LISTS_DIR / f"{key}.html"
    out_path.write_text(html, encoding="utf-8")
    names = parse_names_from_html(html)

    catalog = _read_catalog()
    catalog_lists = catalog.get("lists", {})
    prior = catalog_lists.get(key, {})
    catalog_lists[key] = {
        "category": category or prior.get("category", ""),
        "label": label or prior.get("label", key),
        "list_url": prior.get("list_url", ""),
        "alphabetical_url": prior.get("alphabetical_url", ""),
        "last_updated": last_updated or prior.get("last_updated", ""),
        "downloaded_at": _utc_now_iso(),
        "name_count": len(names),
        "names": names,
        "source": "manual",
        "needs_manual_upload": False,
        "last_error": "",
    }
    catalog["lists"] = catalog_lists
    catalog["index_fetched_at"] = catalog.get("index_fetched_at", _utc_now_iso())
    _write_catalog(catalog)

    names_by_list = {k: meta.get("names", []) for k, meta in catalog_lists.items()}
    total = _write_consolidated(names_by_list)
    _clear_screening_cache()
    return {
        "key": key,
        "name_count": len(names),
        "total_names": total,
    }


def _existing_name_count() -> int:
    if CONSOLIDATED_NAMES_PATH.exists():
        return sum(1 for line in CONSOLIDATED_NAMES_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
    # Fall back to the bundled Iran list count if we have nothing else yet.
    from utils.kyc_store import load_iran_sanctions_names

    return len(load_iran_sanctions_names())


# --- Screening API ---------------------------------------------------------

@lru_cache(maxsize=1)
def _load_consolidated_names() -> frozenset[str]:
    if CONSOLIDATED_NAMES_PATH.exists():
        text = CONSOLIDATED_NAMES_PATH.read_text(encoding="utf-8")
        names = {_normalize_name(line) for line in text.splitlines() if line.strip()}
        if names:
            return frozenset(names)
    # Fallback to the bundled Iran list so screening still works offline.
    from utils.kyc_store import load_iran_sanctions_names

    return load_iran_sanctions_names()


def _clear_screening_cache() -> None:
    _load_consolidated_names.cache_clear()


def _list_key_for_name(name: str) -> str | None:
    catalog = _read_catalog().get("lists", {})
    for key, meta in catalog.items():
        if name in {_normalize_name(n) for n in meta.get("names", [])}:
            return meta.get("label") or key
    return None


def screen_name(full_name: str) -> dict:
    """Return ``{matched, matched_name, list_key}`` for a candidate name."""
    normalized = _normalize_name(full_name)
    if not normalized:
        return {"matched": False, "matched_name": "", "list_key": None}

    sanctions = _load_consolidated_names()
    if normalized in sanctions:
        return {
            "matched": True,
            "matched_name": normalized,
            "list_key": _list_key_for_name(normalized) or "MAS Sanctions",
        }
    for entry in sanctions:
        if entry in normalized or normalized in entry:
            return {
                "matched": True,
                "matched_name": entry,
                "list_key": _list_key_for_name(entry) or "MAS Sanctions",
            }
    return {"matched": False, "matched_name": "", "list_key": None}

"""
MAS sanctions list sync.

Pipeline (built incrementally):

1. **Index** — fetch the MAS TFS table and discover every UN sanctions list link.
2. **Landing** — open each list URL (UN materials page) and cache the HTML.
3. **Download** — locate the “List in alphabetical order” HTML export on each UN page and save it.
4. **Parse** — extract designated names into per-list ``.txt`` files and ``names_consolidated.txt`` for KYC screening.

``screen_name`` is the public API used by the rest of the app.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

MAS_INDEX_URL = (
    "https://www.mas.gov.sg/regulation/anti-money-laundering/"
    "targeted-financial-sanctions/lists-of-designated-individuals-and-entities"
)

DATA_DIR = Path("data/mas_sanctions")
LISTS_DIR = DATA_DIR / "lists"
LANDINGS_DIR = LISTS_DIR / "landings"
CATALOG_PATH = DATA_DIR / "catalog.json"
LAST_SYNC_PATH = DATA_DIR / "last_sync.json"
CONSOLIDATED_NAMES_PATH = DATA_DIR / "names_consolidated.txt"

# Local UN export filenames (scsanctions legacy HTML) mapped to MAS catalog keys.
LIST_FILE_ALIASES: dict[str, str] = {
    "al-qaida_all_name_legacy": "isil-da-esh-and-al-qaida-list",
    "libya_all_name_legacy": "un-1970-list",
    "somalia_all_name_legacy": "un-1844-list",
    "southsudan_all_name_legacy": "un-2206-list",
    "sudan_all_name_legacy": "un-1591-list",
    "taliban_all_name_legacy": "un-1988-taliban-list",
    "yemen_all_name_legacy": "un-2140-list",
}

# Default metadata when a list file exists but MAS index has no entry yet.
EXTRA_CATALOG_DEFAULTS: dict[str, dict[str, str]] = {
    "un-1988-taliban-list": {
        "label": "UN 1988 Taliban List",
        "category": "Counter-Terrorism",
        "list_url": "https://www.un.org/securitycouncil/sanctions/1988/materials",
    },
}

# Hosts that host downloadable UN Security Council sanctions list pages.
UN_SANCTIONS_HOST_SUFFIXES = (
    "un.org",
    "main.un.org",
)

# Singapore statute links in the List column (e.g. TSFA First Schedule) — not UN exports.
SKIP_LIST_HOSTS = (
    "sso.agc.gov.sg",
    "agc.gov.sg",
)

REQUEST_TIMEOUT_SECONDS = 15
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
class SanctionsListRef:
    """One sanctions list discovered on the MAS index table."""

    key: str
    category: str
    label: str
    list_url: str
    last_updated: str
    source: str = "mas_index"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ListLandingPage:
    """Cached HTML from opening a list's UN landing page."""

    ref: SanctionsListRef
    status: str  # "ok" | "failed"
    http_status: int | None = None
    html: str = ""
    fetched_at: str = ""
    error: str | None = None
    landing_path: str = ""

    def to_dict(self) -> dict:
        payload = {
            "status": self.status,
            "http_status": self.http_status,
            "fetched_at": self.fetched_at,
            "error": self.error,
            "landing_path": self.landing_path,
            **self.ref.to_dict(),
        }
        return payload


@dataclass
class ListHtmlDownload:
    """Downloaded alphabetical-order HTML export for one sanctions list."""

    ref: SanctionsListRef
    status: str  # "ok" | "failed"
    download_url: str = ""
    html_path: str = ""
    fetched_at: str = ""
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "download_url": self.download_url,
            "html_path": self.html_path,
            "fetched_at": self.fetched_at,
            "error": self.error,
            **self.ref.to_dict(),
        }


@dataclass
class SyncResult:
    status: str  # "ok", "partial", "skipped", "failed", "needs_upload"
    lists_updated: list[str]
    name_count: int
    error: str | None = None
    fetched_at: str | None = None
    lists_discovered: int = 0
    landings_fetched: int = 0
    html_downloads: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "lists_updated": self.lists_updated,
            "name_count": self.name_count,
            "error": self.error,
            "fetched_at": self.fetched_at or _utc_now_iso(),
            "lists_discovered": self.lists_discovered,
            "landings_fetched": self.landings_fetched,
            "html_downloads": self.html_downloads,
        }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LISTS_DIR.mkdir(parents=True, exist_ok=True)
    LANDINGS_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().upper())


_UN_NAME_BLOCK_RE = re.compile(
    r"<strong>Name:\s*</strong>(.*?)"
    r"(?=<br\s*/?>|<strong\s*>Name\s*\(original|<strong\s*>\s*&nbsp;A\.k\.a\.)",
    re.IGNORECASE | re.DOTALL,
)
_UN_NAME_PART_RE = re.compile(r"\d+:\s*([^<]+?)(?=\s+\d+:\s*|$)")


def _strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _is_na_name_part(value: str) -> bool:
    return value.strip().lower() == "na"


def _combine_numbered_name_parts(raw: str) -> str | None:
    parts: list[str] = []
    for match in _UN_NAME_PART_RE.finditer(raw):
        part = re.sub(r"\s+", " ", match.group(1).strip())
        if part and not _is_na_name_part(part):
            parts.append(part)
    if not parts:
        return None
    return _normalize_name(" ".join(parts))


def _parse_un_sc_export_names(html: str) -> list[str]:
    """Extract primary individual and entity names from a UN scsanctions HTML export."""
    names: list[str] = []
    seen: set[str] = set()

    for match in _UN_NAME_BLOCK_RE.finditer(html):
        raw = _strip_html_tags(match.group(1)).strip()
        if not raw:
            continue

        if re.match(r"^\s*1:\s*", raw, re.IGNORECASE):
            name = _combine_numbered_name_parts(raw)
        else:
            name = _normalize_name(raw)

        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)

    return names


def _parse_mas_table_names(html: str) -> list[str]:
    """Fallback parser for simple MAS-style alphabetical HTML tables."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    names: list[str] = []
    seen: set[str] = set()

    for selector in ("table tr td", "ol li", "ul li", "p"):
        nodes = soup.select(selector)
        if not nodes:
            continue
        for node in nodes:
            text = node.get_text(" ", strip=True)
            if not text or len(text) < 3:
                continue
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


def list_names_txt_path(html_path: str | Path) -> Path:
    return Path(html_path).with_suffix(".txt")


def write_list_names_file(html_path: str | Path, names: list[str]) -> Path:
    _ensure_dirs()
    txt_path = list_names_txt_path(html_path)
    txt_path.write_text(
        "\n".join(names) + ("\n" if names else ""),
        encoding="utf-8",
    )
    return txt_path


def parse_names_from_html(html: str) -> list[str]:
    """Extract designated names from a downloaded sanctions list HTML export."""
    if "<strong>Name:" in html or "<strong>name:" in html.lower():
        names = _parse_un_sc_export_names(html)
        if names:
            return names
    return _parse_mas_table_names(html)


def parse_names_from_file(html_path: str | Path) -> list[str]:
    path = Path(html_path)
    content = path.read_text(encoding="utf-8")
    names = parse_names_from_upload(content, filename=path.name)
    write_list_names_file(path.with_suffix(".txt"), names)
    return names


def _is_html_content(content: str) -> bool:
    head = content[:4000].lower()
    return (
        "<html" in head
        or "<strong>name:" in head
        or ("<table" in head and "name:" in head)
    )


def _parse_plain_name_list(content: str, *, filename: str = "") -> list[str]:
    """Extract one name per line, or from the first CSV/TSV name column."""
    import csv
    from io import StringIO

    suffix = Path(filename).suffix.lower() if filename else ""
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        name = _normalize_name(raw)
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    if suffix == ".csv" or (suffix == ".tsv" or ("\t" in content and "," not in content.splitlines()[0])):
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.reader(StringIO(content), delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return names

        header = [cell.strip().lower() for cell in rows[0]]
        name_idx = 0
        for idx, cell in enumerate(header):
            if "name" in cell:
                name_idx = idx
                break
        else:
            name_idx = 0

        start = 1 if header and header[name_idx] in {"name", "full name", "fullname", "entity"} else 0
        for row in rows[start:]:
            if not row or name_idx >= len(row):
                continue
            _add(row[name_idx])
        return names

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower() in {"name", "full name", "fullname", "entity", "individual"}:
            continue
        if "\t" in stripped:
            stripped = stripped.split("\t", 1)[0].strip()
        elif "," in stripped and suffix == ".csv":
            stripped = stripped.split(",", 1)[0].strip()
        _add(stripped)

    return names


def parse_names_from_upload(content: str, *, filename: str = "") -> list[str]:
    """Flexibly extract names from HTML exports, plain text, or CSV uploads."""
    if _is_html_content(content):
        names = parse_names_from_html(content)
        if names:
            return names
    plain = _parse_plain_name_list(content, filename=filename)
    if plain:
        return plain
    return parse_names_from_html(content)


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


def fetch_mas_index() -> str:
    """Download the MAS sanctions index page HTML."""
    return _fetch(MAS_INDEX_URL)


def _normalize_list_url(href: str) -> str:
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return "https://www.mas.gov.sg" + href
    return href


def is_un_sanctions_list_url(url: str) -> bool:
    """
    Return True for UN Security Council sanctions list URLs linked from the MAS table.

    Excludes Singapore statute links such as the TSFA First Schedule on sso.agc.gov.sg.
    """
    parsed = urlparse(_normalize_list_url(url))
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if any(skip in host for skip in SKIP_LIST_HOSTS):
        return False
    if not any(host.endswith(suffix) or host == suffix for suffix in UN_SANCTIONS_HOST_SUFFIXES):
        return False
    return "securitycouncil" in path and (
        "sanctions" in path or "aq_sanctions_list" in path
    )


def _extract_dates_from_cell(cell) -> list[str]:
    """Pull date strings from the Last Updated column (may contain multiple <br>)."""
    raw = cell.get_text("\n", strip=True)
    dates: list[str] = []
    for line in raw.splitlines():
        text = re.sub(r"\s+", " ", line).strip()
        if text and re.search(r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b", text):
            dates.append(text)
    return dates


def _extract_list_links_from_cell(list_cell) -> list[tuple[str, str]]:
    """Return ``(label, url)`` pairs for UN sanctions anchors in the List column."""
    links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for anchor in list_cell.find_all("a", href=True):
        href = _normalize_list_url(anchor["href"])
        if not is_un_sanctions_list_url(href):
            continue
        if href in seen_urls:
            continue
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        if not label:
            continue
        seen_urls.add(href)
        links.append((label, href))
    return links


def discover_sanctions_lists(html: str) -> list[SanctionsListRef]:
    """
    Parse the MAS index table and return every UN sanctions list linked in column 3.

    Rows may contain multiple list links (e.g. Counter-Terrorism). Non-UN links
    such as the TSFA First Schedule are ignored.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    refs: list[SanctionsListRef] = []
    seen_keys: set[str] = set()
    current_category = ""

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 4:
                continue

            if any(cell.name == "th" for cell in cells):
                continue

            category_text = cells[0].get_text(" ", strip=True)
            if category_text:
                current_category = category_text

            list_links = _extract_list_links_from_cell(cells[2])
            if not list_links:
                continue

            dates = _extract_dates_from_cell(cells[3])
            for index, (label, href) in enumerate(list_links):
                key = _slugify(label)
                if not key or key in seen_keys:
                    suffix = 2
                    base = key or _slugify(current_category)
                    while f"{base}-{suffix}" in seen_keys:
                        suffix += 1
                    key = f"{base}-{suffix}" if base else f"list-{suffix}"

                seen_keys.add(key)
                refs.append(
                    SanctionsListRef(
                        key=key,
                        category=current_category,
                        label=label,
                        list_url=href,
                        last_updated=dates[index] if index < len(dates) else "",
                    )
                )
    return refs


def parse_index_catalog(html: str) -> list[dict[str, str]]:
    """Backward-compatible dict view of :func:`discover_sanctions_lists`."""
    return [ref.to_dict() for ref in discover_sanctions_lists(html)]


def fetch_list_landing_page(ref: SanctionsListRef | dict[str, str]) -> ListLandingPage:
    """Open a single list URL (UN materials page) and return the landing HTML."""
    if isinstance(ref, dict):
        ref = SanctionsListRef(
            key=ref["key"],
            category=ref.get("category", ""),
            label=ref.get("label", ""),
            list_url=ref["list_url"],
            last_updated=ref.get("last_updated", ""),
        )

    fetched_at = _utc_now_iso()
    try:
        html = _fetch(ref.list_url)
        if _looks_like_maintenance(html):
            raise RuntimeError("landing page returned maintenance/unavailable content")

        _ensure_dirs()
        landing_path = LANDINGS_DIR / f"{ref.key}.html"
        landing_path.write_text(html, encoding="utf-8")

        return ListLandingPage(
            ref=ref,
            status="ok",
            http_status=200,
            html=html,
            fetched_at=fetched_at,
            landing_path=str(landing_path),
        )
    except Exception as exc:  # noqa: BLE001 - per-list fault tolerance
        return ListLandingPage(
            ref=ref,
            status="failed",
            fetched_at=fetched_at,
            error=str(exc),
        )


def fetch_all_list_landing_pages(
    refs: list[SanctionsListRef] | list[dict[str, str]],
) -> list[ListLandingPage]:
    """Open every discovered list link and cache each UN landing page."""
    landings: list[ListLandingPage] = []
    for ref in refs:
        if isinstance(ref, dict):
            ref = SanctionsListRef(
                key=ref["key"],
                category=ref.get("category", ""),
                label=ref.get("label", ""),
                list_url=ref["list_url"],
                last_updated=ref.get("last_updated", ""),
            )
        landings.append(fetch_list_landing_page(ref))
    return landings


def crawl_mas_sanctions_index(fetch_landings: bool = True) -> dict:
    """
    Framework entry point: MAS index → discover lists → open each UN page.

    Name extraction from downloaded HTML is intentionally not implemented yet.
    """
    index_html = fetch_mas_index()
    if _looks_like_maintenance(index_html):
        raise RuntimeError("MAS index is in maintenance mode")

    refs = discover_sanctions_lists(index_html)
    landings: list[ListLandingPage] = []
    if fetch_landings and refs:
        landings = fetch_all_list_landing_pages(refs)

    return {
        "index_fetched_at": _utc_now_iso(),
        "lists_discovered": len(refs),
        "lists": [ref.to_dict() for ref in refs],
        "landings": [landing.to_dict() for landing in landings],
        "landings_ok": sum(1 for landing in landings if landing.status == "ok"),
        "landings_failed": sum(1 for landing in landings if landing.status == "failed"),
    }


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


def find_alphabetical_html_download(landing_html: str, base_url: str) -> str | None:
    """
    Find the HTML export URL for the sanctions list in alphabetical order.

  UN committee pages label the section ``List in alphabetical order`` and expose
    PDF / XML / HTML buttons. We want the **HTML** link from that section only
    (not the “by Permanent Reference Number” block).
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(landing_html, "html.parser")

    for heading in soup.find_all(["h3", "h4", "h5"]):
        heading_text = heading.get_text(" ", strip=True).lower()
        if "alphabetical" not in heading_text:
            continue

        nodes_to_search = []
        if heading.parent is not None:
            nodes_to_search.append(heading.parent)
        sibling = heading.find_next_sibling()
        while sibling is not None and sibling.name not in {"h3", "h4", "h5"}:
            nodes_to_search.append(sibling)
            sibling = sibling.find_next_sibling()

        for node in nodes_to_search:
            for anchor in node.find_all("a", href=True):
                if anchor.get_text(" ", strip=True).lower() != "html":
                    continue
                return urljoin(base_url, anchor["href"].strip())

    # Legacy MAS-hosted pages: direct ``.html`` link mentioning alphabetical.
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        text = anchor.get_text(" ", strip=True).lower()
        if href.lower().endswith(".html") and "alphabetical" in f"{text} {href.lower()}":
            return urljoin(base_url, href)

    return None


def find_alphabetical_html(list_page_html: str, base_url: str) -> str | None:
    """Backward-compatible alias for :func:`find_alphabetical_html_download`."""
    return find_alphabetical_html_download(list_page_html, base_url)


def fetch_alphabetical_list_html(
    ref: SanctionsListRef | dict[str, str],
    landing_html: str,
) -> ListHtmlDownload:
    """Download the alphabetical-order HTML export linked from a UN landing page."""
    if isinstance(ref, dict):
        ref = SanctionsListRef(
            key=ref["key"],
            category=ref.get("category", ""),
            label=ref.get("label", ""),
            list_url=ref["list_url"],
            last_updated=ref.get("last_updated", ""),
        )

    fetched_at = _utc_now_iso()
    download_url = find_alphabetical_html_download(landing_html, ref.list_url)
    if not download_url:
        return ListHtmlDownload(
            ref=ref,
            status="failed",
            fetched_at=fetched_at,
            error="no alphabetical-order HTML link found on landing page",
        )

    try:
        html = _fetch(download_url)
        if _looks_like_maintenance(html):
            raise RuntimeError("HTML export returned maintenance/unavailable content")

        _ensure_dirs()
        html_path = LISTS_DIR / f"{ref.key}.html"
        html_path.write_text(html, encoding="utf-8")

        return ListHtmlDownload(
            ref=ref,
            status="ok",
            download_url=download_url,
            html_path=str(html_path),
            fetched_at=fetched_at,
        )
    except Exception as exc:  # noqa: BLE001 - per-list fault tolerance
        return ListHtmlDownload(
            ref=ref,
            status="failed",
            download_url=download_url,
            fetched_at=fetched_at,
            error=str(exc),
        )


# --- Sync orchestration ----------------------------------------------------

def _write_consolidated(names_by_list: dict[str, list[str]]) -> int:
    _ensure_dirs()
    seen: set[str] = set()
    for names in names_by_list.values():
        seen.update(names)
    CONSOLIDATED_NAMES_PATH.write_text("\n".join(sorted(seen)), encoding="utf-8")
    _clear_screening_cache()
    return len(seen)


def _list_file_stems() -> set[str]:
    stems: set[str] = set()
    for path in LISTS_DIR.glob("*"):
        if path.suffix.lower() in {".html", ".htm", ".txt", ".csv", ".tsv"}:
            stems.add(path.stem)
    return stems


def _load_names_for_stem(stem: str) -> list[str]:
    txt_path = LISTS_DIR / f"{stem}.txt"
    if txt_path.exists():
        return [
            _normalize_name(line)
            for line in txt_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    for ext in (".html", ".htm"):
        html_path = LISTS_DIR / f"{stem}{ext}"
        if html_path.exists():
            names = parse_names_from_upload(
                html_path.read_text(encoding="utf-8"),
                filename=html_path.name,
            )
            write_list_names_file(txt_path, names)
            return names
    return []


def catalog_entry_status(entry: dict) -> str:
    """Human-readable import status for one catalog row."""
    if int(entry.get("name_count", 0) or 0) > 0 or entry.get("names"):
        return "Imported"
    names_txt = entry.get("names_txt_path", "")
    if names_txt and Path(names_txt).exists():
        return "Imported"
    html_path = entry.get("html_path", "")
    if html_path and Path(html_path).exists():
        return "HTML downloaded"
    if entry.get("landing_fetched_at") and entry.get("needs_html_download"):
        return "Landing cached"
    if entry.get("needs_manual_upload"):
        return "Needs upload"
    return "Synced"


def reconcile_catalog_with_local_files() -> dict:
    """
    Link on-disk list files to catalog entries and refresh name counts.

    Handles legacy UN export filenames (e.g. ``al-qaida_all_name_legacy``) by
    mapping them to the MAS catalog keys used on the index page.
    """
    _ensure_dirs()
    catalog = _read_catalog()
    catalog_lists: dict[str, dict] = catalog.setdefault("lists", {})
    updated_keys: list[str] = []
    names_by_list: dict[str, list[str]] = {}
    prior_total = _existing_name_count()

    for stem in sorted(_list_file_stems()):
        names = _load_names_for_stem(stem)
        if not names:
            continue

        catalog_key = LIST_FILE_ALIASES.get(stem, stem)
        entry = dict(catalog_lists.get(catalog_key, {}))
        defaults = EXTRA_CATALOG_DEFAULTS.get(catalog_key, {})

        html_path = next(
            (LISTS_DIR / f"{stem}{ext}" for ext in (".html", ".htm") if (LISTS_DIR / f"{stem}{ext}").exists()),
            None,
        )
        txt_path = LISTS_DIR / f"{stem}.txt"

        entry.update(
            {
                "label": entry.get("label") or defaults.get("label") or stem.replace("_", " ").replace("-", " ").title(),
                "category": entry.get("category") or defaults.get("category", ""),
                "list_url": entry.get("list_url") or defaults.get("list_url", ""),
                "name_count": len(names),
                "names": names,
                "names_txt_path": str(txt_path),
                "needs_manual_upload": False,
                "needs_html_download": False,
                "last_error": "",
                "source": entry.get("source") or "local",
                "downloaded_at": entry.get("downloaded_at") or _utc_now_iso(),
            }
        )
        if html_path:
            entry["html_path"] = str(html_path)
            entry["source_path"] = str(html_path)

        catalog_lists[catalog_key] = entry
        names_by_list[catalog_key] = names
        updated_keys.append(catalog_key)

    for key, entry in catalog_lists.items():
        if int(entry.get("name_count", 0) or 0) > 0 or entry.get("names"):
            entry["needs_manual_upload"] = False
            entry["last_error"] = ""
            names_by_list.setdefault(key, list(entry.get("names", [])))

    catalog["lists"] = catalog_lists
    catalog["reconciled_at"] = _utc_now_iso()
    _write_catalog(catalog)
    total = _write_consolidated(names_by_list)
    if updated_keys or total != prior_total:
        _invalidate_kyc_sanctions_fingerprint()
    return {
        "updated_keys": updated_keys,
        "imported_lists": sum(1 for meta in catalog_lists.values() if int(meta.get("name_count", 0) or 0) > 0),
        "name_count": total,
    }


def _invalidate_kyc_sanctions_fingerprint() -> None:
    try:
        from utils.kyc_store import KYC_META_PATH, _read_generation_meta

        meta = _read_generation_meta()
        meta.pop("sanctions_screen_fingerprint", None)
        KYC_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        KYC_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:
        pass


def _apply_parsed_names(entry: dict) -> list[str]:
    html_path = entry.get("html_path", "")
    if not html_path or not Path(html_path).exists():
        return list(entry.get("names", []))

    names = parse_names_from_file(html_path)
    txt_path = list_names_txt_path(html_path)
    entry["names"] = names
    entry["name_count"] = len(names)
    entry["names_txt_path"] = str(txt_path)
    return names


def rebuild_names_from_downloaded_html() -> dict:
    """Parse every list file under ``lists/`` and rebuild consolidated names."""
    result = reconcile_catalog_with_local_files()
    return {
        "lists_parsed": result["imported_lists"],
        "name_count": result["name_count"],
        "parsed_keys": result["updated_keys"],
    }


def sync_mas_sanctions(force: bool = False) -> SyncResult:
    """
    Poll MAS, open each UN landing page, download alphabetical HTML exports,
    and parse names into per-list ``.txt`` files plus ``names_consolidated.txt``.
    """
    _ensure_dirs()
    catalog = _read_catalog()
    catalog_lists: dict[str, dict] = catalog.get("lists", {})

    try:
        index_html = fetch_mas_index()
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

    refs = discover_sanctions_lists(index_html)
    rows = [ref.to_dict() for ref in refs]
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
    needs_download: list[str] = []
    errors: list[str] = []
    landings_fetched = 0
    html_downloads = 0
    names_by_list: dict[str, list[str]] = {
        key: list(meta.get("names", []))
        for key, meta in catalog_lists.items()
    }

    for row in rows:
        key = row["key"]
        prior = catalog_lists.get(key, {})
        html_path = str(prior.get("html_path", ""))
        index_changed = (
            force
            or key not in catalog_lists
            or prior.get("last_updated") != row["last_updated"]
            or prior.get("list_url") != row["list_url"]
        )
        needs_work = (
            force
            or index_changed
            or not html_path
            or not Path(html_path).exists()
        )

        entry: dict = {
            "category": row["category"],
            "label": row.get("label", ""),
            "list_url": row["list_url"],
            "last_updated": row["last_updated"],
            "landing_path": prior.get("landing_path", ""),
            "landing_fetched_at": prior.get("landing_fetched_at", ""),
            "download_url": prior.get("download_url", ""),
            "html_path": html_path if Path(html_path).exists() else "",
            "downloaded_at": prior.get("downloaded_at", ""),
            "name_count": prior.get("name_count", 0),
            "names": prior.get("names", []),
            "source": prior.get("source", ""),
            "needs_html_download": not bool(prior.get("html_path")),
            "needs_manual_upload": prior.get("needs_manual_upload", False),
            "last_error": prior.get("last_error", ""),
        }

        if not needs_work:
            if entry.get("html_path") and (
                force or not entry.get("names") or not entry.get("name_count")
            ):
                names = _apply_parsed_names(entry)
                names_by_list[key] = names
            catalog_lists[key] = entry
            continue

        landing_html = ""
        if force or index_changed or not entry.get("landing_path") or not Path(
            str(entry.get("landing_path", ""))
        ).exists():
            landing = fetch_list_landing_page(row)
            if landing.status != "ok":
                errors.append(f"{key}: {landing.error}")
                entry["needs_manual_upload"] = True
                entry["last_error"] = landing.error or "landing page fetch failed"
                catalog_lists[key] = entry
                needs_download.append(key)
                continue
            landings_fetched += 1
            landing_html = landing.html
            entry["landing_path"] = landing.landing_path
            entry["landing_fetched_at"] = landing.fetched_at
        else:
            landing_html = Path(str(entry["landing_path"])).read_text(encoding="utf-8")

        downloaded = fetch_alphabetical_list_html(row, landing_html)
        if downloaded.status != "ok":
            errors.append(f"{key}: {downloaded.error}")
            entry["needs_manual_upload"] = True
            entry["needs_html_download"] = True
            entry["last_error"] = downloaded.error or "HTML download failed"
            if downloaded.download_url:
                entry["download_url"] = downloaded.download_url
            catalog_lists[key] = entry
            needs_download.append(key)
            continue

        html_downloads += 1
        entry.update(
            {
                "download_url": downloaded.download_url,
                "html_path": downloaded.html_path,
                "downloaded_at": downloaded.fetched_at,
                "source": "auto",
                "needs_html_download": False,
                "needs_manual_upload": False,
                "last_error": "",
            }
        )
        names = _apply_parsed_names(entry)
        names_by_list[key] = names
        catalog_lists[key] = entry
        lists_updated.append(key)

    for key, entry in catalog_lists.items():
        html_path = entry.get("html_path", "")
        if not html_path or not Path(html_path).exists():
            continue
        txt_path = list_names_txt_path(html_path)
        if key in lists_updated or force or not entry.get("names") or not txt_path.exists():
            names = _apply_parsed_names(entry)
            names_by_list[key] = names

    for html_path in sorted(LISTS_DIR.glob("*.html")):
        list_key = html_path.stem
        if list_key not in names_by_list:
            names_by_list[list_key] = parse_names_from_file(html_path)

    catalog["lists"] = catalog_lists
    catalog["index_fetched_at"] = _utc_now_iso()
    catalog["lists_discovered"] = len(rows)
    _write_catalog(catalog)

    reconcile_catalog_with_local_files()
    total = _existing_name_count()

    if lists_updated and not errors:
        status = "ok" if total else "partial"
    elif lists_updated and errors:
        status = "partial"
    elif errors:
        status = "needs_upload"
    else:
        status = "skipped"

    error_msg = "; ".join(errors) if errors else None
    if needs_download and not error_msg:
        error_msg = f"HTML download pending for: {', '.join(needs_download)}"

    result = SyncResult(
        status=status,
        lists_updated=lists_updated,
        name_count=total,
        error=error_msg,
        lists_discovered=len(rows),
        landings_fetched=landings_fetched,
        html_downloads=html_downloads,
    )
    _write_last_sync(result)
    return result


def list_catalog_entries() -> list[dict]:
    """Return a UI-friendly view of the current catalog."""
    try:
        reconcile_catalog_with_local_files()
    except Exception:
        pass

    catalog = _read_catalog().get("lists", {})
    rows: list[dict] = []
    for key, meta in catalog.items():
        if not isinstance(meta, dict):
            meta = {}
        status = catalog_entry_status(meta)
        rows.append(
            {
                "key": key,
                "category": meta.get("category", ""),
                "label": meta.get("label", ""),
                "list_url": meta.get("list_url", ""),
                "last_updated": meta.get("last_updated", ""),
                "landing_fetched_at": meta.get("landing_fetched_at", ""),
                "download_url": meta.get("download_url", ""),
                "html_path": meta.get("html_path", ""),
                "names_txt_path": meta.get("names_txt_path", ""),
                "downloaded_at": meta.get("downloaded_at", ""),
                "name_count": int(meta.get("name_count", 0) or 0),
                "source": meta.get("source", ""),
                "needs_html_download": bool(meta.get("needs_html_download", False)),
                "needs_manual_upload": status == "Needs upload",
                "status": status,
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
    *,
    filename: str = "",
    rescreen: bool = True,
) -> dict:
    """Persist a manually uploaded name list, rebuild consolidated names, and rescreen KYC."""
    _ensure_dirs()
    key = _slugify(key) or _slugify(label) or "manual-list"
    content = html
    upload_name = filename or f"{key}.txt"
    suffix = Path(upload_name).suffix.lower()

    if suffix in {".html", ".htm"} or _is_html_content(content):
        source_path = LISTS_DIR / f"{key}.html"
    elif suffix:
        source_path = LISTS_DIR / f"{key}{suffix}"
    else:
        source_path = LISTS_DIR / f"{key}.txt"

    source_path.write_text(content, encoding="utf-8")
    names = parse_names_from_upload(content, filename=upload_name)
    names_txt_path = LISTS_DIR / f"{key}.txt"
    names_txt_path.write_text(
        "\n".join(names) + ("\n" if names else ""),
        encoding="utf-8",
    )

    catalog = _read_catalog()
    catalog_lists = catalog.get("lists", {})
    prior = catalog_lists.get(key, {})
    catalog_lists[key] = {
        "category": category or prior.get("category", ""),
        "label": label or prior.get("label", key),
        "list_url": prior.get("list_url", ""),
        "alphabetical_url": prior.get("alphabetical_url", ""),
        "last_updated": last_updated or prior.get("last_updated", ""),
        "source_path": str(source_path),
        "html_path": str(source_path) if source_path.suffix.lower() in {".html", ".htm"} else prior.get("html_path", ""),
        "downloaded_at": _utc_now_iso(),
        "name_count": len(names),
        "names": names,
        "names_txt_path": str(names_txt_path),
        "source": "manual",
        "needs_manual_upload": False,
        "last_error": "",
    }
    catalog["lists"] = catalog_lists
    catalog["index_fetched_at"] = catalog.get("index_fetched_at", _utc_now_iso())
    _write_catalog(catalog)

    reconcile_result = reconcile_catalog_with_local_files()
    total = reconcile_result["name_count"]

    rescreen_result = None
    if rescreen:
        from utils.kyc_store import force_rescreen_kyc_sanctions

        rescreen_result = force_rescreen_kyc_sanctions()

    return {
        "key": key,
        "name_count": len(names),
        "total_names": total,
        "names_txt_path": str(names_txt_path),
        "rescreen": rescreen_result,
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
    names: set[str] = set()
    if CONSOLIDATED_NAMES_PATH.exists():
        text = CONSOLIDATED_NAMES_PATH.read_text(encoding="utf-8")
        names.update(_normalize_name(line) for line in text.splitlines() if line.strip())
    # Always union the bundled Iran list so screening works when auto-sync fails.
    from utils.kyc_store import load_iran_sanctions_names

    names.update(load_iran_sanctions_names())
    return frozenset(names)


def _clear_screening_cache() -> None:
    _load_consolidated_names.cache_clear()
    _name_to_list_label.cache_clear()


@lru_cache(maxsize=1)
def _name_to_list_label() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for _key, meta in _read_catalog().get("lists", {}).items():
        label = str(meta.get("label") or _key).strip()
        for name in meta.get("names", []):
            normalized = _normalize_name(name)
            if normalized:
                mapping[normalized] = label
    return mapping


def _list_key_for_name(name: str) -> str | None:
    return _name_to_list_label().get(_normalize_name(name))


def screen_name(full_name: str) -> dict:
    """Return match metadata for a candidate name (exact or fuzzy)."""
    from utils.name_matching import find_best_name_match

    sanctions = _load_consolidated_names()
    return find_best_name_match(
        full_name,
        sanctions,
        list_key_resolver=lambda name: _list_key_for_name(name) or "MAS Sanctions",
    )

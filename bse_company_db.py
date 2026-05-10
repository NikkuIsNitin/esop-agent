"""
BSE company directory.
Primary source: local CSV (BSE_Listed_Companies.csv) — O(1) lookups, 4,800+ companies.
Fallback: live BSE API — used when CSV is missing, stale, or a code/name isn't found.
Both paths return the same dict shape so callers never need to change.
"""
import csv
import time
import requests
from pathlib import Path
from typing import Optional

from config import BSE_HEADERS, BSE_ANNEX_URL

_CSV_PATH = Path(__file__).parent / "BSE_Listed_Companies.csv"

# ── In-memory store (populated from CSV at import) ─────────────────────────────
_by_code: dict[str, dict] = {}
_by_name: dict[str, dict] = {}
_all_entries: list[dict]  = []

# ── BSE live-search endpoints (tried in order) ─────────────────────────────────
_BSE_SEARCH_URL   = "https://api.bseindia.com/BseIndiaAPI/api/GetSearch/w"
_BSE_SCRIP_URL    = "https://api.bseindia.com/BseIndiaAPI/api/ComHeadernewDefault/w"
_BSE_MKTCAP_URL   = "https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w"


# ── CSV loader ─────────────────────────────────────────────────────────────────

def _make_entry(code, name, ticker="", sname="", isin="", group="", status="") -> dict:
    return {
        "bse_code":     str(code).strip().zfill(6),
        "company_name": str(name).strip(),
        "ticker":       str(ticker).strip(),
        "short_name":   str(sname).strip(),
        "isin":         str(isin).strip(),
        "group":        str(group).strip(),
        "status":       str(status).strip(),
    }


def _load():
    global _by_code, _by_name, _all_entries
    if not _CSV_PATH.exists():
        print(f"  BSE CSV not found at {_CSV_PATH} — will use live BSE API for all lookups.")
        return
    with open(_CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code  = str(row.get("Security Code", "")).strip().zfill(6)
            name  = (row.get("Issuer Name",  "") or "").strip()
            instr = (row.get("Instrument",   "") or "").strip()
            if not code or not name:
                continue
            if instr and "equity" not in instr.lower():
                continue
            entry = _make_entry(
                code, name,
                ticker = row.get("Security Id",  ""),
                sname  = row.get("Security Name",""),
                isin   = row.get("ISIN No",      ""),
                group  = row.get("Group",        ""),
                status = row.get("Status",       ""),
            )
            _by_code[code] = entry
            _by_name[name.lower()] = entry
            _all_entries.append(entry)

_load()


# ── Live BSE API helpers ───────────────────────────────────────────────────────

def _bse_get(url: str, params: dict, timeout: int = 8) -> Optional[dict]:
    """GET a BSE API endpoint, return parsed JSON or None."""
    try:
        r = requests.get(url, params=params, headers=BSE_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _parse_search_hit(hit: dict) -> Optional[dict]:
    """
    Convert a raw BSE GetSearch result row into our standard entry dict.
    BSE returns different key names depending on the endpoint.
    """
    code = (
        str(hit.get("SECURITY_CODE") or hit.get("scripcode") or
            hit.get("Scripcode") or hit.get("scrip_code") or "").strip()
    )
    name = (
        str(hit.get("ISSUER_NAME") or hit.get("companyname") or
            hit.get("COMPANYNAME") or hit.get("CmpName") or
            hit.get("LONGNAME") or hit.get("SLONGNAME") or "").strip()
    )
    ticker = (
        str(hit.get("SCRIP_ID") or hit.get("scripid") or
            hit.get("Scripid") or hit.get("scrip_cd") or "").strip()
    )
    isin = str(hit.get("ISIN_NO") or hit.get("isin") or hit.get("ISIN") or "").strip()
    status = str(hit.get("STATUS") or hit.get("status") or "Active").strip()

    if not code or not name:
        return None
    return _make_entry(code, name, ticker=ticker, isin=isin, status=status)


def _lookup_code_via_api(bse_code: str) -> Optional[dict]:
    """
    Resolve a BSE code to a company entry using live BSE APIs.
    Tries three endpoints in order, returns first successful result.
    """
    padded = str(bse_code).strip().zfill(6)

    # 1. GetSearch by code
    data = _bse_get(_BSE_SEARCH_URL, {"strSearch": padded, "strType": "C"})
    if data:
        rows = data if isinstance(data, list) else (data.get("Table") or data.get("data") or [])
        for row in (rows if isinstance(rows, list) else []):
            entry = _parse_search_hit(row)
            if entry and entry["bse_code"].lstrip("0") == padded.lstrip("0"):
                return entry

    # 2. ComHeadernewDefault (company info endpoint)
    data = _bse_get(_BSE_SCRIP_URL, {"scripcode": padded})
    if isinstance(data, dict) and data:
        entry = _parse_search_hit(data)
        if entry:
            return entry

    # 3. BSE Annex API — any recent filing from this scrip carries company name
    from datetime import date, timedelta
    today   = date.today()
    from_dt = (today - timedelta(days=730)).strftime("%Y%m%d")
    to_dt   = today.strftime("%Y%m%d")
    for category in ["Board Meeting", "AGM/EGM", "Annual Report"]:
        params = {
            "strCat":      category,
            "strPrevDate": from_dt,
            "strScrip":    padded,
            "strSearch":   "P",
            "strToDate":   to_dt,
            "strType":     "C",
            "subcategory": "-1",
        }
        data = _bse_get(BSE_ANNEX_URL, params, timeout=12)
        if data:
            filings = data.get("Table", [])
            if filings:
                hit  = filings[0]
                name = (
                    hit.get("SLONGNAME") or hit.get("COMPANYNAME") or
                    hit.get("companyname") or hit.get("LONGNAME") or ""
                ).strip()
                if name:
                    return _make_entry(padded, name)
        time.sleep(0.2)

    return None


def _search_via_api(query: str, max_results: int = 8) -> list[dict]:
    """
    Search BSE for companies matching a name query using the live GetSearch API.
    Returns up to max_results entries.
    """
    data = _bse_get(_BSE_SEARCH_URL, {"strSearch": query, "strType": "C"})
    if not data:
        return []

    rows = data if isinstance(data, list) else (data.get("Table") or data.get("data") or [])
    if not isinstance(rows, list):
        return []

    results = []
    for row in rows:
        entry = _parse_search_hit(row)
        if entry:
            results.append(entry)
        if len(results) >= max_results:
            break
    return results


# ── Public API ─────────────────────────────────────────────────────────────────

def lookup_by_code(bse_code: str) -> Optional[dict]:
    """
    Lookup by BSE security code.
    1. Checks in-memory CSV store (instant).
    2. Falls back to live BSE API if not found.
    """
    code = str(bse_code).strip()
    # CSV path (O(1))
    result = _by_code.get(code) or _by_code.get(code.zfill(6))
    if result:
        return result

    # Live API fallback
    print(f"  BSE code {code} not in CSV — querying BSE API...")
    entry = _lookup_code_via_api(code)
    if entry:
        # Cache it so repeated lookups within the same session are instant
        _by_code[entry["bse_code"]] = entry
        _by_name[entry["company_name"].lower()] = entry
        _all_entries.append(entry)
    return entry


def search_by_name(query: str, max_results: int = 8, active_only: bool = True) -> list[dict]:
    """
    Search companies by partial name or ticker.
    1. Searches in-memory CSV store (ranked: exact > starts-with > contains).
    2. If CSV is empty or returns nothing, falls back to live BSE API search.
    """
    q = query.strip().lower()
    if not q:
        return []

    # CSV path
    if _all_entries:
        exact, starts, contains = [], [], []
        for entry in _all_entries:
            if active_only and entry["status"].lower() not in ("active", ""):
                continue
            n = entry["company_name"].lower()
            t = entry["ticker"].lower()
            if n == q or t == q:
                exact.append(entry)
            elif n.startswith(q) or t.startswith(q):
                starts.append(entry)
            elif q in n or q in t:
                contains.append(entry)
        results = (exact + starts + contains)[:max_results]
        if results:
            return results

    # Live API fallback (CSV empty or no local matches)
    print(f"  No CSV match for '{query}' — querying BSE API...")
    api_results = _search_via_api(query, max_results=max_results)
    # Cache new entries
    for entry in api_results:
        code = entry["bse_code"]
        if code not in _by_code:
            _by_code[code] = entry
            _by_name[entry["company_name"].lower()] = entry
            _all_entries.append(entry)
    return api_results


def total_companies() -> int:
    """Number of companies loaded (CSV + any API-resolved entries this session)."""
    return len(_by_code)


def csv_loaded() -> bool:
    """True if the local CSV was found and loaded."""
    return _CSV_PATH.exists() and len(_by_code) > 100

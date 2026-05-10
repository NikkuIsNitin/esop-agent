import json
import requests
import time
from pathlib import Path
from config import BSE_HEADERS, BSE_ANNEX_URL, BSE_PDF_BASE, DATA_DIR

ANNUAL_REPORT_KEYWORDS = [
    "annual report", "agm notice", "integrated report",
    "annual general meeting notice", "annual report & accounts",
    "annual report and accounts", "annual general meeting",
    # SEBI Regulation 34 = annual report submission mandate (many companies cite only this)
    "regulation 34", "regulations 30 and 34", "regulation 34(1)",
]
# Terms that clearly indicate this is NOT the annual report
NON_REPORT_KEYWORDS = [
    "scrutinizer", "voting result", "voting results",
    "postal ballot", "outcome of board", "financial results",
    "quarterly results", "half yearly", "unaudited",
    "proceedings of agm", "proceedings of annual general",
]
MIN_ANNUAL_REPORT_SIZE = 2_000_000  # 2MB minimum

# BSE categories to search in priority order
SEARCH_CATEGORIES = ["AGM/EGM", "Annual Report"]


def _score_filing(filing: dict) -> int:
    """Score a filing — higher = more likely to be the annual report PDF."""
    score = 0
    headline = (filing.get("HEADLINE", "") or filing.get("NEWSSUB", "")).lower()
    attachment = filing.get("ATTACHMENTNAME") or filing.get("NEWATTACHMENT") or ""
    size = filing.get("Fld_Attachsize") or 0

    if not attachment:
        return -1  # no PDF, skip

    # Enforce minimum size — any legitimate annual report is at least 2MB
    if size < MIN_ANNUAL_REPORT_SIZE:
        return -1

    # Negative score for clearly non-annual-report filings
    for bad in NON_REPORT_KEYWORDS:
        if bad in headline:
            score -= 8

    for kw in ANNUAL_REPORT_KEYWORDS:
        if kw in headline:
            score += 10

    # Size tiers — larger files are more likely to be full annual reports
    if size >= MIN_ANNUAL_REPORT_SIZE:
        score += 5
    if size >= 5_000_000:
        score += 5
    if size >= 15_000_000:
        score += 10   # 15MB+ is almost certainly the annual report
    if size >= 25_000_000:
        score += 5    # extra reward for very large reports

    return score


def _fetch_category(bse_code: str, from_date: str, to_date: str, category: str) -> list:
    """Fetch filings for a date range and category. Returns [] on failure."""
    params = {
        "strCat": category,
        "strPrevDate": from_date,
        "strScrip": bse_code,
        "strSearch": "P",
        "strToDate": to_date,
        "strType": "C",
        "subcategory": "-1",
    }
    try:
        resp = requests.get(BSE_ANNEX_URL, params=params, headers=BSE_HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json().get("Table", [])
    except Exception as e:
        print(f"    BSE API error ({category} {from_date}–{to_date}): {e}")
        return []


def get_annual_report_urls(bse_code: str, years: list[int]) -> dict[int, str]:
    """
    Returns {fiscal_year: filing_info} for each requested year.
    Searches multiple BSE categories to maximize coverage.
    FY{year} = April {year-1} to March {year}, typically filed Apr-Dec of {year}.
    """
    results = {}

    for year in years:
        all_filings: list[dict] = []
        seen_attachments: set[str] = set()

        def add_filings(filings: list):
            for f in filings:
                att = f.get("ATTACHMENTNAME") or f.get("NEWATTACHMENT") or ""
                if att and att not in seen_attachments:
                    all_filings.append(f)
                    seen_attachments.add(att)

        def has_strong_candidate() -> bool:
            return any(
                _score_filing(f) >= 15
                or (_score_filing(f) > 0 and (f.get("Fld_Attachsize") or 0) >= 15_000_000)
                for f in all_filings
            )

        # Primary search: Apr-Dec of the same calendar year (covers most companies)
        for category in SEARCH_CATEGORIES:
            filings = _fetch_category(bse_code, f"{year}0401", f"{year}1231", category)
            add_filings(filings)
            time.sleep(0.2)
            if has_strong_candidate():
                break  # found a good report, skip remaining categories

        # Fallbacks: only run if primary search didn't find a good candidate
        if not has_strong_candidate():
            # Jan-Mar of next year (some companies hold AGM late)
            for category in SEARCH_CATEGORIES:
                filings = _fetch_category(bse_code, f"{year+1}0101", f"{year+1}0331", category)
                add_filings(filings)
                time.sleep(0.2)
                if has_strong_candidate():
                    break

        if not has_strong_candidate():
            # Oct-Dec of previous year (early AGM filers)
            filings = _fetch_category(bse_code, f"{year-1}1001", f"{year-1}1231", "AGM/EGM")
            add_filings(filings)
            time.sleep(0.2)

        # Score and pick best candidate.
        # Require score >= 15 (needs at least one keyword match + size, or very large file)
        # OR score > 0 with size >= 15MB (clearly a large document even with no keywords).
        # This prevents small-but-valid-size files with no keyword evidence from being chosen.
        candidates = [
            (f, _score_filing(f)) for f in all_filings
            if _score_filing(f) >= 0
            and (
                _score_filing(f) >= 15
                or (_score_filing(f) > 0 and (f.get("Fld_Attachsize") or 0) >= 15_000_000)
            )
        ]
        candidates.sort(key=lambda x: x[1], reverse=True)

        if candidates:
            best, score = candidates[0]
            attachment = best.get("ATTACHMENTNAME") or best.get("NEWATTACHMENT")
            headline = best.get("HEADLINE", "") or best.get("NEWSSUB", "")
            size_mb = (best.get("Fld_Attachsize") or 0) / 1_000_000
            pdf_url = BSE_PDF_BASE + attachment
            bse_filing_page = f"https://www.bseindia.com/stock-share-price/company/{bse_code}/"
            results[year] = {
                "pdf_url": pdf_url,
                "bse_page": bse_filing_page,
                "headline": headline,
                "size_mb": round(size_mb, 1),
            }
            print(f"  FY{year} (score={score}, {size_mb:.1f}MB): {headline[:65]}")
        else:
            print(f"  FY{year}: no filing found (company may not have existed yet)")

        time.sleep(0.7)

    return results


def save_url_map(bse_code: str, url_map: dict) -> Path:
    """Persist the URL map so it's available at query time without re-fetching."""
    path = DATA_DIR / f"{bse_code}_url_map.json"
    path.write_text(json.dumps(url_map, indent=2))
    return path


def load_url_map(bse_code: str) -> dict:
    """Load saved URL map. Returns {} if not found."""
    path = DATA_DIR / f"{bse_code}_url_map.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


def get_company_sector_info(bse_code: str) -> dict:
    # ── Fast path: local BSE CSV (covers all 4800+ listed companies instantly) ──
    try:
        from bse_company_db import lookup_by_code
        entry = lookup_by_code(bse_code)
        if entry and entry.get("company_name"):
            return {
                "company_name": entry["company_name"],
                "sector":       "",
                "industry":     "",
                "market_cap":   "",
                "ticker":       entry.get("ticker", ""),
                "isin":         entry.get("isin", ""),
            }
    except Exception:
        pass
    # ── Slow path: BSE API + filings fallback (for codes not in CSV) ──────────
    return _get_company_sector_info_api(bse_code)


def _get_company_sector_info_api(bse_code: str) -> dict:
    """
    Fetch company name and sector from BSE.
    Strategy (in order):
      1. Multiple BSE company-info API endpoints
      2. Filings-based lookup — search BSE annex for recent filings and read
         the company name from the filing metadata (this API is known-good)
    Returns {} only if everything fails.
    """
    _NAME_KEYS   = [
        "CmpName", "companyname", "COMPANYNAME", "CompanyName",
        "LONGNAME", "SLONGNAME", "scrip_name", "scripname",
        "SCRIP_CD_NAME", "Company_Name", "Cmpname", "COMNAME",
    ]
    _SECTOR_KEYS = [
        "Sector", "sector_name", "Industry", "industry_name",
        "Indus", "SectorName", "IndustryName",
    ]

    def _extract(data: dict) -> dict:
        name   = next((str(data[k]).strip() for k in _NAME_KEYS   if data.get(k) and str(data[k]).strip()), "")
        sector = next((str(data[k]).strip() for k in _SECTOR_KEYS if data.get(k) and str(data[k]).strip()), "")
        return {
            "company_name": name,
            "sector":       sector,
            "industry":     data.get("Industry", "") or data.get("Indus", "") or sector,
            "market_cap":   data.get("mktcap", "") or data.get("Mktcap", ""),
        }

    def _try_endpoint(url: str, params: dict) -> dict:
        try:
            resp = requests.get(url, params=params, headers=BSE_HEADERS, timeout=12)
            resp.raise_for_status()
            raw = resp.json()
            if isinstance(raw, list):
                candidates = raw
            elif isinstance(raw, dict) and "Table" in raw:
                candidates = raw["Table"] if isinstance(raw["Table"], list) else [raw]
            else:
                candidates = [raw]
            for item in candidates:
                if isinstance(item, dict):
                    r = _extract(item)
                    if r["company_name"]:
                        return r
        except Exception as e:
            print(f"  BSE API {url}: {e}")
        return {}

    # ── Pass 1: BSE company-info endpoints (short timeout — most fail) ───────
    # Use 4s timeout so we fail fast and reach the reliable filings fallback
    def _try_endpoint_fast(url: str, params: dict) -> dict:
        try:
            resp = requests.get(url, params=params, headers=BSE_HEADERS, timeout=4)
            resp.raise_for_status()
            raw = resp.json()
            if isinstance(raw, list):
                candidates = raw
            elif isinstance(raw, dict) and "Table" in raw:
                candidates = raw["Table"] if isinstance(raw["Table"], list) else [raw]
            else:
                candidates = [raw]
            for item in candidates:
                if isinstance(item, dict):
                    r = _extract(item)
                    if r["company_name"]:
                        return r
        except Exception:
            pass
        return {}

    for url, params in [
        ("https://api.bseindia.com/BseIndiaAPI/api/ComHeadernewDefault/w", {"scripcode": bse_code}),
        ("https://api.bseindia.com/BseIndiaAPI/api/GetSearch/w",           {"strSearch": bse_code, "strType": "C"}),
    ]:
        result = _try_endpoint_fast(url, params)
        if result.get("company_name"):
            return result

    # ── Pass 2: filing-based lookup (uses the same annex API that ALWAYS works) ──
    # Search for any recent Board Meeting / Annual Report / Corp. Action filing
    # from this scrip — the response includes the company's full name.
    from datetime import date, timedelta
    today    = date.today()
    from_dt  = (today - timedelta(days=1095)).strftime("%Y%m%d")  # 3 years back
    to_dt    = today.strftime("%Y%m%d")

    for category in ["Board Meeting", "AGM/EGM", "Annual Report", "Corp. Action"]:
        params = {
            "strCat":      category,
            "strPrevDate": from_dt,
            "strScrip":    bse_code,
            "strSearch":   "P",
            "strToDate":   to_dt,
            "strType":     "C",
            "subcategory": "-1",
        }
        try:
            resp = requests.get(BSE_ANNEX_URL, params=params, headers=BSE_HEADERS, timeout=20)
            resp.raise_for_status()
            filings = resp.json().get("Table", [])
            if filings:
                first = filings[0]
                # BSE annex filings usually have SLONGNAME or COMPANYNAME
                name = (
                    first.get("SLONGNAME") or first.get("COMPANYNAME") or
                    first.get("companyname") or first.get("LONGNAME") or
                    first.get("CmpName") or first.get("COMNAME") or ""
                )
                if name and name.strip():
                    print(f"  Resolved {bse_code} via filings ({category}): {name.strip()}")
                    return {"company_name": name.strip(), "sector": "", "industry": "", "market_cap": ""}
        except Exception as e:
            print(f"  Filing lookup ({category}): {e}")
        time.sleep(0.3)

    return {}


def list_all_filings_for_debug(bse_code: str, year: int) -> dict:
    """Debug: return all filings across all categories for a given year."""
    result = {}
    for category in SEARCH_CATEGORIES + ["Corp. Action", "Board Meeting"]:
        filings = _fetch_category(bse_code, f"{year}0101", f"{year}1231", category)
        result[category] = filings
    return result

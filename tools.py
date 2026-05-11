"""
Tool implementations callable by the Claude agent.
Each tool returns a dict with 'status', 'text', and optionally 'table', 'chart', 'excel_path'.
"""
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go

from database import init_db, add_company, get_all_companies, get_stats, get_recent_runs
from updater import run_update_cycle, check_new_reports, process_pending
from bse_fetcher import get_annual_report_urls, load_url_map, save_url_map, get_company_sector_info
from bse_company_db import lookup_by_code, search_by_name, total_companies
from config import DATA_DIR

# ── Sector → competitor mapping (BSE codes + names) ──────────────────────────
SECTOR_COMPANIES: dict[str, list[tuple[str, str]]] = {
    "IT Software": [
        ("532540", "Tata Consultancy Services"),
        ("500209", "Infosys"),
        ("507685", "Wipro"),
        ("532281", "HCL Technologies"),
        ("532755", "Tech Mahindra"),
        ("540005", "LTIMindtree"),
        ("526299", "Mphasis"),
        ("533179", "Persistent Systems"),
        ("532756", "Coforge"),
        ("542651", "KPIT Technologies"),
    ],
    "Consumer Internet": [
        ("543320", "Zomato"),
        ("543396", "Paytm"),
        ("543095", "Nykaa"),
        ("543530", "PolicyBazaar"),
        ("535648", "Info Edge"),
        ("543400", "MapMyIndia"),
        ("544050", "Swiggy"),
        ("543842", "Ola Electric"),
    ],
    "Banking": [
        ("500180", "HDFC Bank"),
        ("532174", "ICICI Bank"),
        ("500247", "Kotak Mahindra Bank"),
        ("532215", "Axis Bank"),
        ("500112", "State Bank of India"),
        ("532187", "IndusInd Bank"),
        ("500116", "Bank of Baroda"),
        ("532149", "Federal Bank"),
    ],
    "FMCG": [
        ("500875", "ITC"),
        ("500696", "Hindustan Unilever"),
        ("500790", "Nestle India"),
        ("500825", "Britannia Industries"),
        ("500096", "Dabur India"),
        ("500820", "Asian Paints"),
        ("500114", "Titan Company"),
        ("523241", "Marico"),
    ],
    "Automobile": [
        ("532500", "Maruti Suzuki"),
        ("500570", "Tata Motors"),
        ("532977", "Bajaj Auto"),
        ("500182", "Hero MotoCorp"),
        ("500520", "Mahindra & Mahindra"),
        ("500124", "Eicher Motors"),
        ("520056", "TVS Motor"),
    ],
    "Pharma": [
        ("524715", "Sun Pharmaceutical"),
        ("500124", "Dr Reddy's Laboratories"),
        ("500087", "Cipla"),
        ("532488", "Divi's Laboratories"),
        ("500257", "Lupin"),
        ("524804", "Ipca Laboratories"),
        ("540180", "Alkem Laboratories"),
    ],
    "Finance / NBFC": [
        ("500034", "Bajaj Finance"),
        ("532978", "Bajaj Finserv"),
        ("526327", "Cholamandalam Investment"),
        ("533519", "Muthoot Finance"),
        ("573153", "Jio Financial Services"),
    ],
    "Insurance": [
        ("540777", "HDFC Life Insurance"),
        ("543412", "Life Insurance Corporation"),
        ("540719", "SBI Life Insurance"),
        ("541367", "ICICI Prudential Life"),
        ("543104", "Star Health Insurance"),
        ("543269", "Go Digit General Insurance"),
    ],
    "Telecom": [
        ("532454", "Bharti Airtel"),
        ("532822", "Vodafone Idea"),
        ("500900", "Bharti Hexacom"),
        ("532975", "Indus Towers"),
    ],
    "Energy / Oil & Gas": [
        ("500325", "Reliance Industries"),
        ("500312", "ONGC"),
        ("530965", "Indian Oil Corporation"),
        ("532360", "Adani Green Energy"),
        ("543974", "NTPC Green Energy"),
        ("502355", "Tata Power"),
    ],
    "Real Estate": [
        ("523656", "DLF"),
        ("519552", "Godrej Properties"),
        ("543271", "Macrotech Developers (Lodha)"),
        ("503960", "Oberoi Realty"),
        ("542399", "Embassy Office Parks REIT"),
    ],
    "Infrastructure / Capital Goods": [
        ("500510", "Larsen & Toubro"),
        ("500550", "Siemens"),
        ("500116", "ABB India"),
        ("532488", "Thermax"),
        ("543258", "Adani Ports"),
    ],
}

# Reverse map: BSE code → sector for quick lookup
_BSE_TO_SECTOR: dict[str, str] = {
    code: sector
    for sector, companies in SECTOR_COMPANIES.items()
    for code, _ in companies
}

init_db()


# ── Tool definitions for Claude ───────────────────────────────────────────────

TOOLS = [
    {
        "name": "list_tracked_companies",
        "description": "List all companies currently being tracked by the agent, with their status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_annual_report_links",
        "description": (
            "Get year-wise annual report PDF links for a company from BSE. "
            "Returns a table with fiscal year, report headline, file size, and direct PDF URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 500209"},
                "company_name": {"type": "string", "description": "Company name e.g. Infosys"},
            },
            "required": ["bse_code"],
        },
    },
    {
        "name": "get_company_esop_data",
        "description": (
            "Retrieve extracted ESOP data for a tracked company. "
            "Returns scheme-wise data across years with key metrics and a chart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 500209"},
                "company_name": {"type": "string", "description": "Company name e.g. Infosys"},
            },
            "required": ["bse_code"],
        },
    },
    {
        "name": "add_and_fetch_company",
        "description": (
            "Add a new company to the tracking list, fetch its annual reports from BSE, "
            "and extract ESOP data. This may take several minutes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 532540"},
                "company_name": {"type": "string", "description": "Company name e.g. TCS"},
            },
            "required": ["bse_code", "company_name"],
        },
    },
    {
        "name": "extract_esop_data",
        "description": (
            "Re-extract (or extract for the first time) structured ESOP data from already-downloaded "
            "annual report PDFs for a company, and generate/refresh the Excel report. "
            "Use this when the user asks to extract data, refresh data, or generate the Excel sheet."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 500209"},
                "company_name": {"type": "string", "description": "Company name e.g. Infosys"},
            },
            "required": ["bse_code", "company_name"],
        },
    },
    {
        "name": "query_esop_data",
        "description": (
            "Answer any specific question about a company's ESOP data. "
            "Returns raw structured data (all schemes × all years × all fields) so you can answer "
            "questions like: % ownership in FY2024, vesting period, comparison across years, "
            "options exercised by scheme, wealth creation, etc. Use this for targeted questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 500209"},
                "company_name": {"type": "string", "description": "Company name e.g. Infosys"},
                "question":     {"type": "string", "description": "The specific question to answer"},
            },
            "required": ["bse_code", "question"],
        },
    },
    {
        "name": "update_company",
        "description": (
            "Check BSE for new annual reports for ONE specific company and download + extract any new ones. "
            "Much faster than run_update_now when the user asks to update a specific company."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 543320"},
                "company_name": {"type": "string", "description": "Company name e.g. Zomato"},
            },
            "required": ["bse_code", "company_name"],
        },
    },
    {
        "name": "run_update_now",
        "description": "Check BSE for new annual reports for ALL tracked companies. Use update_company instead if the user mentions a specific company.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_dashboard_stats",
        "description": "Get overall statistics: companies tracked, reports processed, recent runs.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_bse_company",
        "description": (
            "Look up a company by name OR by BSE code. "
            "If given a numeric BSE code (e.g. 500002), resolves it to the company name via BSE API. "
            "Call this whenever the user provides only a BSE code and you need the company name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name": {
                    "type": "string",
                    "description": "Company name OR numeric BSE code (e.g. '500002' or 'Infosys')"
                },
            },
            "required": ["company_name"],
        },
    },
    {
        "name": "check_esop_status",
        "description": (
            "Instantly check whether a company has an ESOP / stock option plan or not. "
            "Returns YES, NO, or UNKNOWN with evidence. Call this whenever the user asks "
            "'does X have ESOPs?', 'does X give stock options?', 'ESOP status of X', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code e.g. 532540"},
                "company_name": {"type": "string", "description": "Company name e.g. TCS"},
            },
            "required": ["bse_code"],
        },
    },
    {
        "name": "get_sector_competitors",
        "description": (
            "Identify the sector/industry of a company and list its major listed competitors. "
            "Shows which competitors are already tracked and which have ESOP data ready. "
            "Call this when the user asks 'who are X's competitors?', 'what sector is X in?', "
            "'compare X with peers', or 'show me IT sector companies'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE code of the company"},
                "company_name": {"type": "string", "description": "Company name"},
            },
            "required": [],
        },
    },
    {
        "name": "generate_instant_report",
        "description": (
            "Generate a complete ESOP Excel report for ANY BSE-listed company instantly — "
            "no prior setup needed. Fetches the last 5 annual reports from BSE, "
            "extracts all ESOP data with AI, and produces a downloadable Excel. "
            "Use this when the user gives a BSE code and wants an immediate report "
            "without going through the full add/track pipeline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_code":     {"type": "string", "description": "BSE security code e.g. 532540"},
                "company_name": {"type": "string", "description": "Optional — auto-resolved from BSE code"},
            },
            "required": ["bse_code"],
        },
    },
    {
        "name": "compare_esop_companies",
        "description": (
            "Side-by-side ESOP comparison across multiple companies or an entire sector. "
            "Shows: has ESOP yes/no, number of schemes, total options granted, outstanding, exercised. "
            "Call when the user asks to compare ESOPs across companies or a sector."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bse_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of BSE codes to compare. Leave empty to compare all tracked companies.",
                },
                "sector": {
                    "type": "string",
                    "description": "Sector name (e.g. 'IT Software') to compare all companies in that sector.",
                },
            },
            "required": [],
        },
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_company(inp: dict):
    """
    Find a company by bse_code or name.
    Resolution order:
      1. Exact BSE code match in tracked-companies DB
      2. Name fuzzy match in tracked-companies DB
      3. BSE CSV database (instant, 4800+ companies)
      4. BSE API / filings fallback
    Returns (bse_code, name).
    """

    bse_code     = inp.get("bse_code", "").strip()
    company_name = inp.get("company_name", "")
    companies    = get_all_companies()

    # 1 & 2 — tracked DB
    match = next((c for c in companies if c["bse_code"] == bse_code), None)
    if not match and company_name:
        match = next(
            (c for c in companies if company_name.lower() in c["company_name"].lower()), None
        )
    if match:
        return match["bse_code"], match["company_name"]

    # 3 — BSE CSV (instant)
    if bse_code.isdigit():
        entry = lookup_by_code(bse_code)
        if entry:
            return bse_code, entry["company_name"]
    if not bse_code and company_name:
        hits = search_by_name(company_name, max_results=1)
        if hits:
            return hits[0]["bse_code"], hits[0]["company_name"]

    # 4 — API fallback (slow, only for codes not in CSV)
    if bse_code.isdigit() and not company_name:
        info = get_company_sector_info(bse_code)
        resolved = info.get("company_name", "")
        if resolved:
            return bse_code, resolved

    return bse_code, company_name


# ── Tool implementations ──────────────────────────────────────────────────────

def list_tracked_companies(_: dict) -> dict:
    companies = get_all_companies()
    if not companies:
        return {"status": "ok", "text": "No companies tracked yet. Add one to get started."}
    rows = []
    for c in companies:
        from database import get_conn
        conn = get_conn()
        total = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE bse_code=?", (c["bse_code"],)
        ).fetchone()[0]
        done = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE bse_code=? AND status='done'", (c["bse_code"],)
        ).fetchone()[0]
        conn.close()
        rows.append({
            "BSE Code":     c["bse_code"],
            "Company":      c["company_name"],
            "Reports Found": total,
            "Extracted":    done,
            "Last Checked": (c.get("last_checked") or "Never")[:16],
        })
    return {"status": "ok", "table": rows, "text": f"{len(companies)} companies tracked."}


def get_annual_report_links(inp: dict) -> dict:
    bse_code, company_name = _resolve_company(inp)
    if not bse_code:
        return {"status": "error", "text": "BSE code required."}

    # Load cached url_map first
    url_map = load_url_map(bse_code)

    # If empty or very few years, try fetching fresh from BSE
    if len(url_map) < 2:
        try:
            current_year = 2025
            years = list(range(current_year - 5, current_year + 1))
            url_map = get_annual_report_urls(bse_code, years)
            if url_map:
                save_url_map(bse_code, url_map)
        except Exception as e:
            if not url_map:
                return {"status": "error", "text": f"Could not fetch report links: {e}"}

    if not url_map:
        return {"status": "ok", "text": f"No annual reports found for BSE code {bse_code}."}

    rows = []
    for yr in sorted(url_map.keys(), reverse=True):
        info = url_map[yr]
        fy_label = f"FY {int(yr)-1}-{str(yr)[-2:]}"
        headline = (info.get("headline") or "")[:80]
        size = info.get("size_mb") or 0
        pdf_url = info.get("pdf_url", "")
        rows.append({
            "Fiscal Year": fy_label,
            "Report":      headline + ("..." if len(info.get("headline","")) > 80 else ""),
            "Size (MB)":   f"{size:.1f}" if size else "—",
            "PDF Link":    pdf_url,
        })

    name_label = company_name or f"BSE {bse_code}"
    text = f"**{name_label}** — {len(rows)} annual report(s) found on BSE:\n\n"
    for r in rows:
        text += f"- **{r['Fiscal Year']}** ({r['Size (MB)']} MB): {r['PDF Link']}\n"

    return {
        "status": "ok",
        "text":  text,
        "table": rows,
    }


def get_company_esop_data(inp: dict) -> dict:
    bse_code, company_name = _resolve_company(inp)
    if not bse_code:
        return {"status": "error", "text": "BSE code required."}
    if not company_name:
        return {"status": "error", "text": f"Company '{bse_code}' not found in tracked list. Add it first."}

    company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
    excel_path = company_dir / "ESOP_data.xlsx"
    if not excel_path.exists():
        return {"status": "error", "text": f"No extracted data for {company_name}. Run extract first."}

    try:
        xl = pd.ExcelFile(excel_path)
        sheets = xl.sheet_names
        scheme_sheets = [s for s in sheets if s not in ("FY wise", "KMP ESOPs")]

        summary_rows, chart_data = [], {}
        for sheet in scheme_sheets:
            df = xl.parse(sheet, header=None)
            if df.empty or len(df) < 3:
                continue
            years = [str(y) for y in df.iloc[1, 1:] if pd.notna(y)]
            data_df = df.iloc[2:]

            granted_row = data_df[data_df.iloc[:, 0].astype(str).str.contains("Granted", na=False)]
            if not granted_row.empty:
                granted_vals = granted_row.iloc[0, 1:1+len(years)].tolist()
                chart_data[sheet] = {"years": years, "granted": granted_vals}
                for y, g in zip(years, granted_vals):
                    summary_rows.append({"Scheme": sheet, "Year": y, "Options Granted": g})

        fig = None
        if chart_data:
            colors = ["#2E75B6", "#FFC000", "#70AD47", "#ED7D31", "#9B59B6"]
            fig = go.Figure()
            for i, (scheme, data) in enumerate(chart_data.items()):
                fig.add_trace(go.Bar(
                    name=scheme, x=data["years"],
                    y=[v if isinstance(v, (int, float)) and pd.notna(v) else 0 for v in data["granted"]],
                    marker_color=colors[i % len(colors)],
                ))
            fig.update_layout(
                title=f"{company_name} — Options Granted by Year & Scheme",
                barmode="group", xaxis_title="Fiscal Year", yaxis_title="Options Granted",
                height=400, plot_bgcolor="white", paper_bgcolor="white",
                font=dict(family="Arial"),
            )

        return {
            "status": "ok",
            "text": (
                f"ESOP data for **{company_name}** — "
                f"{len(scheme_sheets)} scheme(s) across {len(years)} years.\n"
                f"Switch to the **📊 Data Explorer** tab to see the full formatted table."
            ),
            "table": summary_rows or None,
            "chart": fig,
            "excel_path": str(excel_path),
        }
    except Exception as e:
        return {"status": "error", "text": f"Error reading Excel: {e}"}


def add_and_fetch_company(inp: dict) -> dict:
    bse_code = inp.get("bse_code", "").strip()
    company_name = inp.get("company_name", "").strip()
    if not bse_code or not company_name:
        return {"status": "error", "text": "Both BSE code and company name are required."}

    add_company(bse_code, company_name)
    steps = [f"✅ **{company_name}** ({bse_code}) added to tracking list."]

    try:
        # Step 1: find reports on BSE
        new = check_new_reports(bse_code, company_name)
        if new == 0:
            steps.append("⚠️ No annual reports found on BSE for this company. Check that the BSE code is correct.")
            return {"status": "ok", "text": "\n".join(steps)}

        steps.append(f"📥 Found **{new} annual report(s)** on BSE — downloading PDFs...")

        # Step 2: download + extract
        dl, ex = process_pending(bse_code, company_name)
        steps.append(f"📄 Downloaded: {dl} PDF(s)")
        steps.append(f"🔍 ESOP data extracted from: {ex} report(s)")

        # Step 3: find Excel
        company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
        excel_path  = company_dir / "ESOP_data.xlsx"

        if excel_path.exists():
            xl     = pd.ExcelFile(excel_path)
            sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]
            steps.append(f"📊 Excel report ready — **{len(sheets)} scheme(s)** found: {', '.join(sheets)}")
            steps.append("\n👉 Switch to **📊 Data Explorer** to view the full table and download the Excel.")
            return {
                "status":     "ok",
                "text":       "\n".join(steps),
                "excel_path": str(excel_path),
            }
        else:
            steps.append("⚠️ Excel not generated — extraction may have found no ESOP data in these reports.")
            return {"status": "ok", "text": "\n".join(steps)}

    except Exception as e:
        return {"status": "error", "text": "\n".join(steps) + f"\n\n❌ Error: {e}"}


def extract_esop_data(inp: dict) -> dict:
    """Re-extract structured ESOP data from downloaded PDFs and rebuild the Excel."""
    bse_code = inp.get("bse_code", "").strip()
    company_name = inp.get("company_name", "").strip()
    if not bse_code or not company_name:
        bse_code, company_name = _resolve_company(inp)
    if not bse_code:
        return {"status": "error", "text": "BSE code required."}

    from pdf_downloader import get_pdf_path
    from extractor import extract_all_years, export_to_excel

    # Find all downloaded PDFs
    years = list(range(2020, 2026))
    pdf_paths = {}
    for yr in years:
        p = get_pdf_path(company_name, bse_code, yr)
        if p.exists():
            pdf_paths[yr] = p

    if not pdf_paths:
        return {"status": "error", "text": f"No downloaded PDFs found for {company_name}. Add and fetch the company first."}

    try:
        url_map = load_url_map(bse_code)
        scheme_data, kmp_data, esop_texts = extract_all_years(company_name, pdf_paths, url_map)

        company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
        company_dir.mkdir(parents=True, exist_ok=True)
        excel_path = company_dir / "ESOP_data.xlsx"

        export_to_excel(company_name, scheme_data, kmp_data, sorted(pdf_paths.keys()), excel_path,
                        esop_texts=esop_texts)

        schemes = list(scheme_data.keys())
        return {
            "status": "ok",
            "text": (
                f"✅ **{company_name}** — ESOP data extracted and Excel generated.\n"
                f"- Years processed: {sorted(pdf_paths.keys())}\n"
                f"- Schemes found: {', '.join(schemes)}\n"
                f"- KMP records: {len(kmp_data)}\n\n"
                f"Go to **📊 Data Explorer** to view, or download the Excel below."
            ),
            "excel_path": str(excel_path),
        }
    except Exception as e:
        return {"status": "error", "text": f"Extraction failed: {e}"}


def query_esop_data(inp: dict) -> dict:
    """Read full Excel data into a structured dict and return it for Claude to answer any question."""
    bse_code, company_name = _resolve_company(inp)
    question = inp.get("question", "")

    if not company_name:
        return {"status": "error", "text": f"Company not found in tracked list. Add it first."}

    company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
    excel_path  = company_dir / "ESOP_data.xlsx"
    if not excel_path.exists():
        return {"status": "error", "text": f"No extracted data for {company_name}. Add and extract first."}

    try:
        xl = pd.ExcelFile(excel_path)
        scheme_sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]

        # Build full structured data: scheme → year → field → value
        all_data = {}
        for sheet in scheme_sheets:
            df = xl.parse(sheet, header=None)
            if df.empty or len(df) < 3:
                continue
            years = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
            scheme_dict = {}
            for ri in range(2, len(df)):
                label = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
                if not label or label in ("nan", "None"):
                    continue
                row_vals = {}
                for ci, yr in enumerate(years):
                    val = df.iloc[ri, ci + 1] if ci + 1 < len(df.columns) else None
                    if pd.notna(val) and str(val) not in ("nan", "None", ""):
                        row_vals[yr] = val
                if row_vals:
                    scheme_dict[label] = row_vals
            all_data[sheet] = {"years": years, "data": scheme_dict}

        # KMP data
        kmp_data = []
        if "KMP ESOPs" in xl.sheet_names:
            kmp_df = xl.parse("KMP ESOPs")
            if not kmp_df.empty:
                kmp_data = kmp_df.fillna("—").to_dict(orient="records")

        # Build structured text for Claude to reason over.
        # Format: one value per line so Claude can parse each field cleanly.
        lines = [
            f"━━ ESOP DATA: {company_name} (BSE {bse_code}) ━━",
            f"Question to answer: {question}" if question else "",
            f"Schemes found: {', '.join(all_data.keys()) if all_data else 'None'}",
            "",
        ]

        for scheme, sdata in all_data.items():
            lines.append(f"┌─ Scheme: {scheme} ─────────────────────────")
            lines.append(f"│  Fiscal years with data: {', '.join(sdata['years'])}")
            for field, yr_vals in sdata["data"].items():
                vals_str = "  |  ".join(
                    f"FY{yr[-2:]}: {v}" for yr, v in sorted(yr_vals.items())
                )
                lines.append(f"│  {field}: {vals_str}")
            lines.append("└───────────────────────────────────────────")
            lines.append("")

        if kmp_data:
            lines.append("┌─ KMP Individual Grants ────────────────────")
            for row in kmp_data[:50]:
                parts = [f"{k}={v}" for k, v in row.items() if v and str(v) != "—"]
                lines.append("│  " + " | ".join(parts))
            lines.append("└───────────────────────────────────────────")

        if not all_data and not kmp_data:
            lines.append(
                "NO ESOP DATA FOUND.\n"
                "Possible reasons:\n"
                "  1. Company has no active ESOP/stock option plan\n"
                "  2. Annual reports not yet downloaded — run update first\n"
                "  3. ESOP data in PDF is in an image/scanned format (not text-extractable)\n"
                "Please inform the user clearly which case applies."
            )

        data_text = "\n".join(l for l in lines if l is not None)

        return {
            "status":     "ok",
            "text":       data_text,
            "question":   question,
            "company":    company_name,
            "excel_path": str(excel_path),
        }

    except Exception as e:
        return {"status": "error", "text": f"Error reading data: {e}"}


def update_company(inp: dict) -> dict:
    """Update a single company — faster than run_update_now for targeted updates."""
    bse_code = inp.get("bse_code", "").strip()
    company_name = inp.get("company_name", "").strip()
    if not bse_code or not company_name:
        bse_code, company_name = _resolve_company(inp)
    if not bse_code:
        return {"status": "error", "text": "BSE code required."}

    steps = [f"🔄 Checking BSE for new **{company_name}** reports..."]
    try:
        new = check_new_reports(bse_code, company_name)
        if new == 0:
            steps.append("✅ Already up to date — no new reports found on BSE.")
            return {"status": "ok", "text": "\n".join(steps)}

        steps.append(f"📥 Found **{new} new report(s)** — downloading...")
        dl, ex = process_pending(bse_code, company_name)
        steps.append(f"📄 Downloaded: {dl} | Extracted: {ex}")

        company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
        excel_path  = company_dir / "ESOP_data.xlsx"
        if excel_path.exists():
            xl = pd.ExcelFile(excel_path)
            schemes = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]
            steps.append(f"📊 Excel updated — {len(schemes)} scheme(s): {', '.join(schemes)}")
            steps.append("👉 Switch to **📊 Data Explorer** to view.")
            return {"status": "ok", "text": "\n".join(steps), "excel_path": str(excel_path)}
        else:
            steps.append("⚠️ No structured ESOP data found in the new reports.")
            return {"status": "ok", "text": "\n".join(steps)}
    except Exception as e:
        return {"status": "error", "text": "\n".join(steps) + f"\n❌ Error: {e}"}


def run_update_now(_: dict) -> dict:
    try:
        result = run_update_cycle()
        return {
            "status": "ok",
            "text": (
                f"Update complete.\n"
                f"- Companies checked: {result.get('companies_checked', 0)}\n"
                f"- New reports found: {result.get('new_reports', 0)}\n"
                f"- Downloaded: {result.get('downloaded', 0)}\n"
                f"- Extracted: {result.get('extracted', 0)}\n"
                f"- Errors: {result.get('errors', 0)}"
            ),
        }
    except Exception as e:
        return {"status": "error", "text": f"Update failed: {e}"}


def get_dashboard_stats(_: dict) -> dict:
    stats = get_stats()
    runs = get_recent_runs(3)
    run_text = "\n".join([f"- {r['run_at'][:16]}: {r['summary']}" for r in runs]) or "No runs yet."
    return {
        "status": "ok",
        "text": (
            f"**Dashboard Stats**\n"
            f"- Companies tracked: {stats['companies']}\n"
            f"- Total reports in DB: {stats['total']}\n"
            f"- Extracted: {stats['done']}\n"
            f"- Pending: {stats['pending']}\n"
            f"- Failed: {stats['failed']}\n\n"
            f"**Recent Runs:**\n{run_text}"
        ),
        "stats": stats,
    }


def search_bse_company(inp: dict) -> dict:

    name = inp.get("company_name", "").strip()

    # ── Numeric input → treat as BSE code ─────────────────────────────────────
    if name.isdigit():
        entry = lookup_by_code(name)
        if entry:
            cname = entry["company_name"]
            ticker = entry.get("ticker", "")
            isin   = entry.get("isin", "")
            return {
                "status": "ok",
                "text": f"BSE code **{name}** = **{cname}** (Ticker: {ticker} | ISIN: {isin})",
                "table": [{"BSE Code": name, "Company": cname, "Ticker": ticker, "ISIN": isin}],
                "resolved": {"bse_code": name, "company_name": cname},
            }
        # CSV miss — fall back to API
        info = get_company_sector_info(name)
        cname = info.get("company_name", "")
        if cname:
            return {
                "status": "ok",
                "text": f"BSE code **{name}** = **{cname}**",
                "table": [{"BSE Code": name, "Company": cname}],
                "resolved": {"bse_code": name, "company_name": cname},
            }
        return {
            "status": "ok",
            "text": (
                f"BSE code **{name}** not found in the local database ({total_companies()} companies) "
                f"or BSE API. The code may be invalid or delisted. Verify at bseindia.com."
            ),
        }

    # ── Name-based search: use the full BSE CSV database ─────────────────────
    # Covers all 4800+ BSE listed companies
    results = search_by_name(name, max_results=8)
    if results:
        rows = [{"BSE Code": e["bse_code"], "Company": e["company_name"],
                 "Ticker": e["ticker"], "ISIN": e["isin"]} for e in results]
        top = results[0]
        text = (
            f"Found **{len(results)}** match(es) for **'{name}'** "
            f"(searched {total_companies()} BSE-listed companies)."
        )
        return {
            "status": "ok",
            "text":   text,
            "table":  rows,
            "resolved": {"bse_code": top["bse_code"], "company_name": top["company_name"]}
            if len(results) == 1 else None,
        }

    return {
        "status": "ok",
        "text": (
            f"No match found for **'{name}'** in the BSE company database "
            f"({total_companies()} companies). "
            "Try a shorter keyword (e.g. 'infosys', 'tata', 'hdfc') "
            "or provide the BSE code directly."
        ),
    }


_PRESET_REMOVED = True  # preset dict replaced by bse_company_db (4800+ companies)

_DEAD_OLD_PRESET = {  # intentionally unreachable — kept for grep history
        # ── IT / Software ─────────────────────────────────────────────────────
        "infosys":           ("500209", "Infosys"),
        "tcs":               ("532540", "Tata Consultancy Services"),
        "wipro":             ("507685", "Wipro"),
        "hcl":               ("532281", "HCL Technologies"),
        "tech mahindra":     ("532755", "Tech Mahindra"),
        "ltimindtree":       ("540005", "LTIMindtree"),
        "persistent":        ("533179", "Persistent Systems"),
        "mphasis":           ("526299", "Mphasis"),
        "coforge":           ("532756", "Coforge"),
        "kpit":              ("542651", "KPIT Technologies"),
        "oracle financial":  ("532466", "Oracle Financial Services"),
        "mastek":            ("523704", "Mastek"),
        "zensar":            ("504067", "Zensar Technologies"),
        "hexaware":          ("500194", "Hexaware Technologies"),
        "mindtree":          ("532819", "LTIMindtree"),
        # ── Consumer Internet / New Age ────────────────────────────────────────
        "zomato":            ("543320", "Zomato"),
        "paytm":             ("543396", "Paytm"),
        "nykaa":             ("543095", "Nykaa"),
        "policybazaar":      ("543530", "PolicyBazaar"),
        "naukri":            ("535648", "Info Edge"),
        "info edge":         ("535648", "Info Edge"),
        "swiggy":            ("544050", "Swiggy"),
        "mapmy":             ("543400", "MapMyIndia"),
        "ola electric":      ("544176", "Ola Electric"),
        "delhivery":         ("543529", "Delhivery"),
        "fino payments":     ("543386", "Fino Payments Bank"),
        # ── Banking ───────────────────────────────────────────────────────────
        "hdfc bank":         ("500180", "HDFC Bank"),
        "icici bank":        ("532174", "ICICI Bank"),
        "kotak":             ("500247", "Kotak Mahindra Bank"),
        "axis bank":         ("532215", "Axis Bank"),
        "sbi":               ("500112", "State Bank of India"),
        "indusind":          ("532187", "IndusInd Bank"),
        "federal bank":      ("500469", "Federal Bank"),
        "yes bank":          ("532648", "Yes Bank"),
        "bank of baroda":    ("532134", "Bank of Baroda"),
        "punjab national":   ("532461", "Punjab National Bank"),
        "canara bank":       ("532483", "Canara Bank"),
        "idfc first":        ("539437", "IDFC First Bank"),
        "au small":          ("540611", "AU Small Finance Bank"),
        "csb bank":          ("542867", "CSB Bank"),
        "rbl bank":          ("540065", "RBL Bank"),
        # ── Finance / NBFC ────────────────────────────────────────────────────
        "bajaj finance":     ("500034", "Bajaj Finance"),
        "bajaj finserv":     ("532978", "Bajaj Finserv"),
        "muthoot":           ("533519", "Muthoot Finance"),
        "chola":             ("526327", "Cholamandalam Investment"),
        "manappuram":        ("531213", "Manappuram Finance"),
        "shriram finance":   ("511218", "Shriram Finance"),
        "pfc":               ("532810", "Power Finance Corporation"),
        "rec":               ("532955", "REC Limited"),
        "l&t finance":       ("533519", "L&T Finance"),
        "jio financial":     ("543810", "Jio Financial Services"),
        # ── FMCG / Consumer ───────────────────────────────────────────────────
        "itc":               ("500875", "ITC"),
        "hul":               ("500696", "Hindustan Unilever"),
        "hindustan unilever":("500696", "Hindustan Unilever"),
        "nestle":            ("500790", "Nestle India"),
        "britannia":         ("500825", "Britannia Industries"),
        "dabur":             ("500096", "Dabur India"),
        "asian paints":      ("500820", "Asian Paints"),
        "titan":             ("500114", "Titan Company"),
        "marico":            ("531642", "Marico"),
        "colgate":           ("500830", "Colgate-Palmolive India"),
        "emami":             ("531162", "Emami"),
        "godrej consumer":   ("532424", "Godrej Consumer Products"),
        "berger paints":     ("509480", "Berger Paints"),
        "pidilite":          ("500331", "Pidilite Industries"),
        "havells":           ("517354", "Havells India"),
        "varun beverages":   ("540180", "Varun Beverages"),
        "jubilant food":     ("533155", "Jubilant Foodworks"),
        "trent":             ("500251", "Trent"),
        "avenue supermarts": ("540376", "Avenue Supermarts (D-Mart)"),
        "dmart":             ("540376", "Avenue Supermarts (D-Mart)"),
        "bata":              ("500043", "Bata India"),
        "basf":              ("500042", "BASF India"),
        "page industries":   ("532827", "Page Industries"),
        "metro brands":      ("543426", "Metro Brands"),
        "relaxo":            ("530517", "Relaxo Footwears"),
        "united spirits":    ("532432", "Diageo India"),
        "united breweries":  ("532478", "United Breweries"),
        # ── Pharma / Healthcare ───────────────────────────────────────────────
        "sun pharma":        ("524715", "Sun Pharmaceutical"),
        "dr reddy":          ("500124", "Dr Reddy's Laboratories"),
        "cipla":             ("500087", "Cipla"),
        "divi":              ("532488", "Divi's Laboratories"),
        "lupin":             ("500257", "Lupin"),
        "alkem":             ("539523", "Alkem Laboratories"),
        "torrent pharma":    ("500420", "Torrent Pharmaceuticals"),
        "aurobindo":         ("524804", "Aurobindo Pharma"),
        "biocon":            ("532523", "Biocon"),
        "ipca":              ("524494", "Ipca Laboratories"),
        "glenmark":          ("532296", "Glenmark Pharmaceuticals"),
        "mankind pharma":    ("543904", "Mankind Pharma"),
        "zydus":             ("532321", "Zydus Lifesciences"),
        "abbott india":      ("500488", "Abbott India"),
        "pfizer":            ("500680", "Pfizer"),
        "max healthcare":    ("543220", "Max Healthcare Institute"),
        "apollo hospitals":  ("508869", "Apollo Hospitals"),
        "fortis":            ("532843", "Fortis Healthcare"),
        "narayana":          ("539551", "Narayana Hrudayalaya"),
        "metropolis":        ("542650", "Metropolis Healthcare"),
        "dr lal":            ("539524", "Dr Lal PathLabs"),
        # ── Auto / EV ─────────────────────────────────────────────────────────
        "maruti":            ("532500", "Maruti Suzuki"),
        "tata motors":       ("500570", "Tata Motors"),
        "bajaj auto":        ("532977", "Bajaj Auto"),
        "hero":              ("500182", "Hero MotoCorp"),
        "mahindra":          ("500520", "Mahindra & Mahindra"),
        "eicher":            ("505200", "Eicher Motors"),
        "tvs":               ("532343", "TVS Motor"),
        "ashok leyland":     ("500477", "Ashok Leyland"),
        "motherson":         ("517334", "Samvardhana Motherson"),
        "minda industries":  ("532539", "Uno Minda"),
        "bosch":             ("500530", "Bosch"),
        "balkrishna":        ("502355", "Balkrishna Industries"),
        "apollo tyres":      ("500877", "Apollo Tyres"),
        "mrf":               ("500290", "MRF"),
        "ceat":              ("500878", "CEAT"),
        "exide":             ("500086", "Exide Industries"),
        "amara raja":        ("500008", "Amara Raja Energy & Mobility"),
        # ── Energy / Oil & Gas ────────────────────────────────────────────────
        "reliance":          ("500325", "Reliance Industries"),
        "ongc":              ("500312", "ONGC"),
        "ioc":               ("530965", "Indian Oil Corporation"),
        "indian oil":        ("530965", "Indian Oil Corporation"),
        "bpcl":              ("500547", "BPCL"),
        "hpcl":              ("500104", "HPCL"),
        "tata power":        ("500400", "Tata Power"),
        "adani green":       ("541450", "Adani Green Energy"),
        "adani power":       ("533096", "Adani Power"),
        "adani total gas":   ("542066", "Adani Total Gas"),
        "adani enterprises": ("512599", "Adani Enterprises"),
        "adani ports":       ("532921", "Adani Ports"),
        "ntpc":              ("532555", "NTPC"),
        "power grid":        ("532898", "Power Grid Corporation"),
        "coal india":        ("533278", "Coal India"),
        "gail":              ("532155", "GAIL India"),
        "petronet":          ("532522", "Petronet LNG"),
        "Gujarat gas":       ("539336", "Gujarat Gas"),
        # ── Telecom ───────────────────────────────────────────────────────────
        "airtel":            ("532454", "Bharti Airtel"),
        "vodafone":          ("532822", "Vodafone Idea"),
        "indus towers":      ("534816", "Indus Towers"),
        # ── Insurance ─────────────────────────────────────────────────────────
        "hdfc life":         ("540777", "HDFC Life Insurance"),
        "sbi life":          ("540719", "SBI Life Insurance"),
        "lic":               ("543526", "Life Insurance Corporation"),
        "icici prudential":  ("540133", "ICICI Prudential Life"),
        "icici lombard":     ("540716", "ICICI Lombard GIC"),
        "star health":       ("543412", "Star Health Insurance"),
        "go digit":          ("544046", "Go Digit General Insurance"),
        # ── Real Estate ───────────────────────────────────────────────────────
        "dlf":               ("532868", "DLF"),
        "godrej properties": ("533150", "Godrej Properties"),
        "oberoi realty":     ("533273", "Oberoi Realty"),
        "lodha":             ("543271", "Macrotech Developers (Lodha)"),
        "macrotech":         ("543271", "Macrotech Developers (Lodha)"),
        "prestige":          ("535523", "Prestige Estates"),
        "brigade":           ("532929", "Brigade Enterprises"),
        "sobha":             ("532784", "Sobha"),
        "phoenix mills":     ("503100", "Phoenix Mills"),
        # ── Infrastructure / Capital Goods ────────────────────────────────────
        "l&t":               ("500510", "Larsen & Toubro"),
        "larsen":            ("500510", "Larsen & Toubro"),
        "siemens":           ("500550", "Siemens"),
        "abb":               ("500002", "ABB India Limited"),
        "bhel":              ("500103", "BHEL"),
        "cg power":          ("500093", "CG Power & Industrial Solutions"),
        "thermax":           ("500411", "Thermax"),
        "bharat electronics":("500049", "Bharat Electronics"),
        "bel":               ("500049", "Bharat Electronics"),
        "mazagon dock":      ("543237", "Mazagon Dock Shipbuilders"),
        "cochin shipyard":   ("540678", "Cochin Shipyard"),
        "garden reach":      ("542011", "Garden Reach Shipbuilders"),
        "hindustan aeronautics": ("541154", "Hindustan Aeronautics"),
        "hal":               ("541154", "Hindustan Aeronautics"),
        "rails vikas":       ("542649", "Rail Vikas Nigam"),
        "ircon":             ("541956", "IRCON International"),
        "irctc":             ("542830", "IRCTC"),
        # ── Metals / Mining ───────────────────────────────────────────────────
        "tata steel":        ("500470", "Tata Steel"),
        "jswsteel":          ("500228", "JSW Steel"),
        "hindalco":          ("500440", "Hindalco Industries"),
        "vedanta":           ("500295", "Vedanta"),
        "sail":              ("500113", "SAIL"),
        "nmdc":              ("526371", "NMDC"),
        "national aluminium":("532234", "National Aluminium Company"),
        "jindal steel":      ("532286", "Jindal Steel & Power"),
        # ── Cement ────────────────────────────────────────────────────────────
        "ambuja":            ("500425", "Ambuja Cements"),
        "acc":               ("500410", "ACC"),
        "ultratech":         ("532538", "UltraTech Cement"),
        "shree cement":      ("500387", "Shree Cement"),
        "dalmia bharat":     ("542216", "Dalmia Bharat"),
        "jk cement":         ("532644", "JK Cement"),
        # ── Chemicals / Specialty ─────────────────────────────────────────────
        "srf":               ("503806", "SRF"),
        "pi industries":     ("523642", "PI Industries"),
        "atul":              ("500027", "Atul"),
        "navin fluorine":    ("532504", "Navin Fluorine"),
        "deepak nitrite":    ("506401", "Deepak Nitrite"),
        "clean science":     ("543318", "Clean Science & Technology"),
        "fine organics":     ("541557", "Fine Organic Industries"),
        # ── Logistics ─────────────────────────────────────────────────────────
        "aegis":             ("500003", "Aegis Logistics"),
        "blue dart":         ("526612", "Blue Dart Express"),
        "container corp":    ("531344", "Container Corporation of India"),
        "concor":            ("531344", "Container Corporation of India"),
        "mahindra logistics":("540768", "Mahindra Logistics"),
        "gati":              ("532345", "Gati"),
        # ── Consumer Discretionary ────────────────────────────────────────────
        "dixon":             ("541171", "Dixon Technologies"),
        "amber enterprises": ("540902", "Amber Enterprises"),
        "voltas":            ("500575", "Voltas"),
        "blue star":         ("500067", "Blue Star"),
        "crompton":          ("539876", "Crompton Greaves Consumer"),
        "orient electric":   ("541301", "Orient Electric"),
        "kajaria":           ("500233", "Kajaria Ceramics"),
        "cera":              ("532443", "Cera Sanitaryware"),
        "supreme industries":("509930", "Supreme Industries"),
        "astral":            ("532830", "Astral"),
        "polycab":           ("542652", "Polycab India"),
        "finolex cables":    ("500144", "Finolex Cables"),
        # ── Media / Entertainment ─────────────────────────────────────────────
        "zee":               ("505537", "Zee Entertainment"),
        "sun tv":            ("532733", "Sun TV Network"),
        "pvr inox":          ("532689", "PVR Inox"),
        # ── Hotels / Travel ───────────────────────────────────────────────────
        "indian hotels":     ("500850", "Indian Hotels (Taj)"),
        "eih":               ("500840", "EIH (Oberoi Hotels)"),
        "lemon tree":        ("541233", "Lemon Tree Hotels"),
        "thomas cook":       ("500413", "Thomas Cook India"),
        "makemytrip":        ("530132", "MakeMyTrip"),
        # ── Agriculture ───────────────────────────────────────────────────────
        "upl":               ("512070", "UPL"),
        "rallis":            ("500355", "Rallis India"),
        "coromandel":        ("506395", "Coromandel International"),
        "chambal fertilizers":("500085", "Chambal Fertilizers"),
        # ── Conglomerates ─────────────────────────────────────────────────────
        "tata consultancy":  ("532540", "Tata Consultancy Services"),
        "tata consumer":     ("500800", "Tata Consumer Products"),
        "tata chemicals":    ("500770", "Tata Chemicals"),
        "tata communications":("500483", "Tata Communications"),
        "tata elxsi":        ("500408", "Tata Elxsi"),
        "voltas tata":       ("500575", "Voltas"),
        "godrej industries": ("500164", "Godrej Industries"),
        "godrej agrovet":    ("540743", "Godrej Agrovet"),
    }



def check_esop_status(inp: dict) -> dict:
    """
    Quickly determine whether a company has an active ESOP/stock option plan.
    Returns YES / NO / UNKNOWN with supporting evidence.
    """
    bse_code, company_name = _resolve_company(inp)
    if not company_name:
        return {"status": "error", "text": "Company not found. Add it first or provide a valid BSE code."}

    company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
    excel_path  = company_dir / "ESOP_data.xlsx"

    if not excel_path.exists():
        # Check if PDFs are downloaded but not extracted
        from pdf_downloader import get_pdf_path
        has_pdfs = any(get_pdf_path(company_name, bse_code, yr).exists() for yr in range(2020, 2026))
        if has_pdfs:
            return {
                "status": "ok",
                "text": (
                    f"⚠️ **{company_name}** — annual reports are downloaded but ESOP extraction hasn't run yet.\n"
                    "Run **extract_esop_data** first to determine ESOP status."
                ),
            }
        return {
            "status": "ok",
            "text": (
                f"❓ **UNKNOWN** — {company_name} has not been fetched yet.\n"
                "Use **add_and_fetch_company** to download annual reports and extract ESOP data."
            ),
        }

    try:
        xl = pd.ExcelFile(excel_path)
        scheme_sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]

        # Check if any numeric ESOP data actually exists
        has_real_data = False
        active_schemes = []
        for sheet in scheme_sheets:
            df = xl.parse(sheet, header=None)
            if df.empty or len(df) < 3:
                continue
            # Look for any non-null numeric value in data rows
            numeric_vals = df.iloc[2:, 1:].apply(pd.to_numeric, errors="coerce")
            if numeric_vals.notna().any().any() and numeric_vals.sum().sum() > 0:
                has_real_data = True
                active_schemes.append(sheet)

        # KMP ESOP check
        kmp_entries = 0
        if "KMP ESOPs" in xl.sheet_names:
            kmp_df = xl.parse("KMP ESOPs")
            kmp_entries = len(kmp_df.dropna(how="all"))

        if has_real_data:
            lines = [
                f"✅ **YES — {company_name} has an active ESOP plan.**",
                f"",
                f"**Schemes found ({len(active_schemes)}):** {', '.join(active_schemes)}",
            ]
            if kmp_entries:
                lines.append(f"**KMP grant records:** {kmp_entries}")
            lines.append(f"\nUse **query_esop_data** to dive into specific metrics.")
            return {"status": "ok", "text": "\n".join(lines), "excel_path": str(excel_path)}
        else:
            return {
                "status": "ok",
                "text": (
                    f"❌ **NO — {company_name} does not appear to have an active ESOP plan.**\n\n"
                    f"Annual reports were processed but no stock option data was found.\n"
                    f"This is common for traditional large-caps (e.g. PSUs, old-economy companies) "
                    f"that use cash-based or PF-based compensation instead of equity grants."
                ),
            }

    except Exception as e:
        return {"status": "error", "text": f"Error reading ESOP data: {e}"}


def get_sector_competitors(inp: dict) -> dict:
    """
    Identify the sector of a company and list its major listed competitors.
    Shows which competitors are already tracked in this system.
    """
    bse_code, company_name = _resolve_company(inp)
    if not company_name and not bse_code:
        return {"status": "error", "text": "Provide a BSE code or company name."}

    # 1. Try our static map first (instant, no API call)
    sector = _BSE_TO_SECTOR.get(bse_code, "")

    # 2. Fall back to BSE API
    if not sector and bse_code:
        info = get_company_sector_info(bse_code)
        sector = info.get("sector") or info.get("industry") or ""
        if not company_name:
            company_name = info.get("company_name", bse_code)

    # 3. Try partial name match against our sector map
    if not sector and company_name:
        cname_lower = company_name.lower()
        for sec, companies in SECTOR_COMPANIES.items():
            for _, cname in companies:
                if cname_lower in cname.lower() or cname.lower() in cname_lower:
                    sector = sec
                    break
            if sector:
                break

    if not sector:
        return {
            "status": "ok",
            "text": (
                f"⚠️ Could not auto-detect sector for **{company_name or bse_code}**.\n\n"
                "Known sectors:\n" +
                "\n".join(f"  • {s}" for s in SECTOR_COMPANIES.keys()) +
                "\n\nTry: 'Who are Zomato's competitors?' or 'IT sector ESOP comparison'"
            ),
        }

    competitors = SECTOR_COMPANIES.get(sector, [])
    rows = []
    for code, cname in competitors:
        is_self = (code == bse_code or cname.lower() == (company_name or "").lower())
        # Check if we already have ESOP data locally (quick disk check, no API)
        excel = DATA_DIR / f"{code}_{cname.replace(' ', '_')}" / "ESOP_data.xlsx"
        esop_known = "📊 Data available" if excel.exists() else "—"
        rows.append({
            "BSE Code": code,
            "Company":  cname + (" ◀ (selected)" if is_self else ""),
            "ESOP Data": esop_known,
        })

    peers = [r["Company"].replace(" ◀ (selected)", "") for r in rows if "◀" not in r["Company"]]

    lines = [
        f"🏭 **Sector: {sector}**",
        f"**{company_name or bse_code}** has **{len(peers)}** listed peer(s) in this sector:",
        "",
        " · ".join(peers),
        "",
        "Use **generate_instant_report** on any peer's BSE code for its ESOP data.",
        "Use **compare_esop_companies** with multiple BSE codes for side-by-side comparison.",
    ]

    return {
        "status": "ok",
        "text":   "\n".join(lines),
        "table":  rows,
        "sector": sector,
        "peers":  [(r["BSE Code"], r["Company"].replace(" ◀ (selected)", "")) for r in rows if "◀" not in r["Company"]],
    }


def compare_esop_companies(inp: dict) -> dict:
    """
    Side-by-side ESOP comparison across multiple companies.
    Shows: schemes count, total grants, outstanding options, dilution %, latest FY data.
    """
    bse_codes = inp.get("bse_codes", [])  # list of BSE codes
    sector    = inp.get("sector", "")     # OR compare all companies in a sector

    # Build list of (bse_code, company_name) pairs to compare
    tracked = {c["bse_code"]: c["company_name"] for c in get_all_companies()}

    if sector and not bse_codes:
        sector_companies = SECTOR_COMPANIES.get(sector, [])
        bse_codes = [code for code, _ in sector_companies if code in tracked]

    if not bse_codes:
        # Default: compare all tracked companies
        bse_codes = list(tracked.keys())

    if len(bse_codes) < 2:
        return {
            "status": "ok",
            "text": (
                "Need at least 2 companies with extracted data to compare.\n"
                "Add more companies first, or specify a sector like: compare_esop_companies with sector='IT Software'"
            ),
        }

    rows = []
    chart_companies, chart_grants = [], []

    for code in bse_codes:
        cname = tracked.get(code, code)
        excel = DATA_DIR / f"{code}_{cname.replace(' ', '_')}" / "ESOP_data.xlsx"

        if not excel.exists():
            rows.append({
                "Company": cname, "BSE Code": code,
                "Status": "No data", "Schemes": "—",
                "Latest FY": "—", "Total Granted": "—",
                "Outstanding": "—", "Exercised": "—",
                "Has ESOP": "❓",
            })
            continue

        try:
            xl = pd.ExcelFile(excel)
            scheme_sheets = [s for s in xl.sheet_names if s not in ("FY wise", "KMP ESOPs")]

            total_granted     = 0
            total_outstanding = 0
            total_exercised   = 0
            latest_fy         = "—"
            has_esop          = False

            for sheet in scheme_sheets:
                df = xl.parse(sheet, header=None)
                if df.empty or len(df) < 3:
                    continue
                years = [str(v) for v in df.iloc[1, 1:] if pd.notna(v)]
                if years:
                    latest_fy = max(years)

                for ri in range(2, len(df)):
                    label = str(df.iloc[ri, 0]) if pd.notna(df.iloc[ri, 0]) else ""
                    if not label:
                        continue
                    vals = df.iloc[ri, 1:].apply(pd.to_numeric, errors="coerce")

                    if "granted" in label.lower():
                        g = vals.sum()
                        if not pd.isna(g) and g > 0:
                            total_granted += int(g)
                            has_esop = True
                    elif "outstanding" in label.lower() and "beginning" not in label.lower():
                        o = vals.dropna().iloc[-1] if not vals.dropna().empty else 0
                        if not pd.isna(o):
                            total_outstanding += int(o)
                    elif "exercised" in label.lower():
                        e = vals.sum()
                        if not pd.isna(e) and e > 0:
                            total_exercised += int(e)

            rows.append({
                "Company":       cname,
                "BSE Code":      code,
                "Has ESOP":      "✅ Yes" if has_esop else "❌ No",
                "Schemes":       len(scheme_sheets),
                "Latest FY":     latest_fy,
                "Total Granted": f"{total_granted:,}" if total_granted else "—",
                "Outstanding":   f"{total_outstanding:,}" if total_outstanding else "—",
                "Exercised":     f"{total_exercised:,}" if total_exercised else "—",
            })

            if has_esop:
                chart_companies.append(cname)
                chart_grants.append(total_granted)

        except Exception as e:
            rows.append({
                "Company": cname, "BSE Code": code,
                "Has ESOP": "❓", "Schemes": "—",
                "Latest FY": "—", "Total Granted": "—",
                "Outstanding": "—", "Exercised": "—",
            })

    # Build comparison chart
    fig = None
    if len(chart_companies) >= 2:
        colors = ["#2E75B6", "#FFC000", "#70AD47", "#ED7D31", "#9B59B6",
                  "#E74C3C", "#1ABC9C", "#F39C12", "#8E44AD", "#2ECC71"]
        fig = go.Figure(go.Bar(
            x=chart_companies,
            y=chart_grants,
            marker_color=colors[:len(chart_companies)],
            text=[f"{g:,}" for g in chart_grants],
            textposition="outside",
        ))
        fig.update_layout(
            title="Total Options Granted — Company Comparison",
            xaxis_title="Company", yaxis_title="Total Options Granted (all years)",
            height=420, plot_bgcolor="white", paper_bgcolor="white",
            font=dict(family="Arial"),
        )

    esop_yes = sum(1 for r in rows if r.get("Has ESOP") == "✅ Yes")
    esop_no  = sum(1 for r in rows if r.get("Has ESOP") == "❌ No")

    return {
        "status": "ok",
        "text": (
            f"📊 **ESOP Comparison — {len(rows)} companies**\n\n"
            f"✅ Have ESOPs: **{esop_yes}** | ❌ No ESOPs: **{esop_no}**\n\n"
            "See table below for full details. Use **query_esop_data** on any company for deeper analysis."
        ),
        "table": rows,
        "chart": fig,
    }


def generate_instant_report(inp: dict) -> dict:
    """
    Instant pipeline: BSE code → fetch URLs → download PDFs → extract → Excel.
    Uses a temp directory; no database writes.
    Returns the Excel path for immediate download.
    """
    import tempfile, time as _time
    from bse_fetcher import get_annual_report_urls
    from pdf_downloader import download_pdf
    from extractor import extract_all_years, export_to_excel

    bse_code = inp.get("bse_code", "").strip()
    if not bse_code:
        return {"status": "error", "text": "BSE code is required."}

    # ── 1. Resolve company name ───────────────────────────────────────────────
    entry = lookup_by_code(bse_code)
    company_name = (entry or {}).get("company_name") or inp.get("company_name", "").strip()
    if not company_name:
        info = get_company_sector_info(bse_code)
        company_name = info.get("company_name", f"BSE_{bse_code}")
    ticker = (entry or {}).get("ticker", "")

    steps = [
        f"⚡ **Instant Report — {company_name}** (BSE: {bse_code})",
        f"Ticker: {ticker}" if ticker else "",
    ]

    # ── 2. Fetch BSE annual report URLs ───────────────────────────────────────
    from datetime import date
    current_fy = date.today().year if date.today().month >= 4 else date.today().year - 1
    years = list(range(current_fy - 4, current_fy + 1))  # last 5 FY years

    steps.append(f"\n📡 Fetching annual report links from BSE for FY{years[0]}–FY{years[-1]}...")
    url_map = get_annual_report_urls(bse_code, years)
    if not url_map:
        return {
            "status": "error",
            "text": "\n".join(s for s in steps if s) + (
                f"\n\n❌ No annual reports found on BSE for {company_name} ({bse_code}). "
                "The company may not file on BSE, or the code may be incorrect."
            ),
        }
    steps.append(f"✅ Found **{len(url_map)} annual report(s)**: FY{sorted(url_map.keys())}")

    # ── 3. Download PDFs to a temp directory ─────────────────────────────────
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"esop_{bse_code}_"))
    steps.append(f"\n📥 Downloading PDFs...")

    pdf_paths, url_infos = {}, {}
    for yr in sorted(url_map.keys()):
        info = url_map[yr]
        pdf_url = info.get("pdf_url", "")
        if not pdf_url:
            continue
        save_path = tmp_dir / f"FY{yr}.pdf"
        ok = download_pdf(pdf_url, save_path)
        if ok:
            pdf_paths[int(yr)] = save_path
            url_infos[str(yr)] = info
            size_mb = save_path.stat().st_size / 1_000_000
            steps.append(f"  ✓ FY{yr} — {size_mb:.1f} MB")
        else:
            steps.append(f"  ✗ FY{yr} — download failed")
        _time.sleep(0.5)

    if not pdf_paths:
        return {
            "status": "error",
            "text": "\n".join(s for s in steps if s) + "\n\n❌ All PDF downloads failed.",
        }

    # ── 4. Extract ESOP data ──────────────────────────────────────────────────
    steps.append(f"\n🔍 Extracting ESOP data from {len(pdf_paths)} report(s)...")
    try:
        scheme_data, kmp_data, esop_texts = extract_all_years(company_name, pdf_paths, url_infos)
    except Exception as e:
        return {
            "status": "error",
            "text": "\n".join(s for s in steps if s) + f"\n\n❌ Extraction failed: {e}",
        }

    # ── 5. Export to Excel (in same temp dir) ─────────────────────────────────
    excel_path = tmp_dir / f"{company_name.replace(' ', '_')}_ESOP_Report.xlsx"
    try:
        export_to_excel(company_name, scheme_data, kmp_data, sorted(pdf_paths.keys()), excel_path,
                        esop_texts=esop_texts)
    except Exception as e:
        return {
            "status": "error",
            "text": "\n".join(s for s in steps if s) + f"\n\n❌ Excel export failed: {e}",
        }

    schemes = list(scheme_data.keys())
    has_esop = bool(schemes)

    # ── 6. Build a rich ESOP summary for the agent to narrate ─────────────────
    esop_summary_lines = []
    scheme_summaries = []
    total_grants_all = 0

    for scheme_name, year_data in scheme_data.items():
        sorted_yrs = sorted(year_data.keys())
        if not sorted_yrs:
            continue
        latest_yr = sorted_yrs[-1]
        d = year_data[latest_yr]

        def _n(v):
            try: return int(float(v)) if v is not None else None
            except: return None
        def _pct(v):
            try: return f"{float(v)*100:.2f}%" if v is not None else None
            except: return None

        total_granted_scheme = sum(
            _n(year_data[yr].get("options_granted")) or 0
            for yr in sorted_yrs
        )
        total_grants_all += total_granted_scheme

        outstanding    = _n(d.get("options_outstanding_end"))
        exercised_last = _n(d.get("options_exercised"))
        dilution       = _pct(d.get("dilution_pct"))
        ownership      = _pct(d.get("ownership_pct"))
        fair_value     = d.get("weighted_avg_fair_value") or d.get("fair_value_per_option")
        stock_price    = d.get("stock_price_at_grant") or d.get("market_price_at_grant")
        pool           = _n(d.get("pool_approved"))

        s_lines = [f"**Scheme: {scheme_name}**"]
        s_lines.append(f"- Years covered: FY{sorted_yrs[0]-1}-{str(sorted_yrs[0])[-2:]} → FY{latest_yr-1}-{str(latest_yr)[-2:]}")
        if pool: s_lines.append(f"- Pool approved: {pool:,} options")
        s_lines.append(f"- Total granted (all years): {total_granted_scheme:,}")
        if outstanding: s_lines.append(f"- Outstanding (latest year-end): {outstanding:,}")
        if exercised_last: s_lines.append(f"- Exercised (latest year): {exercised_last:,}")
        if dilution: s_lines.append(f"- Dilution %: {dilution}")
        if ownership: s_lines.append(f"- Ownership %: {ownership}")
        try:
            if fair_value: s_lines.append(f"- Weighted avg fair value: ₹{float(fair_value):,.2f}")
            if stock_price: s_lines.append(f"- Market price at grant: ₹{float(stock_price):,.2f}")
        except Exception:
            pass

        esop_summary_lines.append("\n".join(s_lines))
        scheme_summaries.append({
            "scheme":              scheme_name,
            "total_granted":       total_granted_scheme,
            "outstanding_latest":  outstanding,
            "dilution_pct":        dilution,
            "ownership_pct":       ownership,
        })

    kmp_names = list({k.get("kmp_name", "") for k in kmp_data if k.get("kmp_name")})

    summary_block = "\n\n".join(esop_summary_lines) if esop_summary_lines else "No ESOP scheme data found in annual reports."
    if kmp_names:
        summary_block += f"\n\n**KMP with ESOP grants ({len(kmp_names)}):** {', '.join(kmp_names[:8])}"

    # Detect sparse data: scheme found but no numerical data extracted
    sparse_data = has_esop and total_grants_all == 0 and not kmp_names

    steps.append(
        f"\n✅ **Report ready!**\n"
        f"- {'✅ Has ESOP' if has_esop else '❌ No ESOP plan found'}\n"
        + (f"- Schemes: {', '.join(schemes)}\n" if schemes else "")
        + f"- Years processed: FY{sorted(pdf_paths.keys())}\n"
        + f"- KMP records: {len(kmp_data)}"
        + (
            "\n\n⚠️ **Note:** ESOP scheme name was detected but detailed numerical data could not be "
            "extracted. This typically means the annual reports are scanned PDFs (image-based, not "
            "text-searchable) or the company uses a non-standard disclosure format. "
            "The Excel file includes the raw ESOP text in the **ESOP Statements** sheet for manual review."
            if sparse_data else ""
        )
    )

    return {
        "status":          "ok",
        "text":            "\n".join(s for s in steps if s),
        "excel_path":      str(excel_path),
        "has_esop":        has_esop,
        "schemes":         schemes,
        "company":         company_name,
        "esop_summary":    summary_block,
        "scheme_details":  scheme_summaries,
        "total_grants":    total_grants_all,
        "kmp_names":       kmp_names,
    }


TOOL_MAP = {
    "list_tracked_companies":  list_tracked_companies,
    "get_annual_report_links": get_annual_report_links,
    "get_company_esop_data":   get_company_esop_data,
    "query_esop_data":         query_esop_data,
    "add_and_fetch_company":   add_and_fetch_company,
    "extract_esop_data":       extract_esop_data,
    "update_company":          update_company,
    "run_update_now":          run_update_now,
    "get_dashboard_stats":     get_dashboard_stats,
    "search_bse_company":      search_bse_company,
    "check_esop_status":       check_esop_status,
    "get_sector_competitors":  get_sector_competitors,
    "compare_esop_companies":  compare_esop_companies,
    "generate_instant_report": generate_instant_report,
}


def execute_tool(name: str, inputs: dict) -> dict:
    fn = TOOL_MAP.get(name)
    if not fn:
        return {"status": "error", "text": f"Unknown tool: {name}"}
    return fn(inputs)

"""
Incremental update agent.
For each tracked company, checks BSE for new annual reports,
downloads any new ones, and runs extraction.
Only processes what's new — already-done reports are skipped.
"""
import time
from datetime import datetime
from pathlib import Path

from config import DATA_DIR, DEFAULT_COMPANY
from bse_fetcher import get_annual_report_urls
from pdf_downloader import download_pdf, get_pdf_path
from extractor import extract_all_years, export_to_excel
from database import (
    init_db, add_company, get_all_companies, update_last_checked,
    is_report_known, upsert_report, mark_downloaded, mark_extracted,
    mark_failed, get_pending_reports, get_stats, log_run,
)

# How many fiscal years back to check
YEARS_TO_CHECK = 5

# Current fiscal year (April–March cycle)
def current_fy() -> int:
    from datetime import date
    today = date.today()
    return today.year if today.month >= 4 else today.year - 1


def check_new_reports(bse_code: str, company_name: str) -> int:
    """
    Checks BSE for annual reports for the last YEARS_TO_CHECK years.
    Skips years already in the DB — only fetches genuinely unknown years.
    Returns count of new reports found.
    """
    fy_end = current_fy()
    all_years = list(range(fy_end - YEARS_TO_CHECK + 1, fy_end + 1))

    # Only hit BSE API for years not already recorded in the DB
    unknown_years = [y for y in all_years if not is_report_known(bse_code, y)]
    if not unknown_years:
        print(f"  {company_name}: all years already tracked, skipping BSE fetch")
        update_last_checked(bse_code)
        return 0

    print(f"  Checking BSE for {company_name} ({bse_code}) — {len(unknown_years)} new year(s): {unknown_years}...")
    url_map = get_annual_report_urls(bse_code, unknown_years)

    new_count = 0
    for year, url_info in url_map.items():
        year = int(year)
        if not is_report_known(bse_code, year):
            upsert_report(bse_code, year, url_info)
            print(f"    New report found: FY{year} — {url_info.get('headline', '')[:60]}")
            new_count += 1
        else:
            print(f"    FY{year}: already tracked, skipping")

    update_last_checked(bse_code)
    return new_count


def process_pending(bse_code: str, company_name: str) -> tuple[int, int]:
    """
    Downloads and extracts any pending reports for one company.
    Returns (downloaded_count, extracted_count).
    """
    pending = get_pending_reports(bse_code)
    if not pending:
        print(f"  No pending reports for {company_name}")
        return 0, 0

    downloaded = 0
    for report in pending:
        year = report["fiscal_year"]
        pdf_url = report["pdf_url"]

        if not pdf_url:
            mark_failed(bse_code, year, "No PDF URL found")
            continue

        pdf_path = get_pdf_path(company_name, bse_code, year)

        success = download_pdf(pdf_url, pdf_path)
        if success:
            mark_downloaded(bse_code, year, str(pdf_path))
            downloaded += 1
        else:
            mark_failed(bse_code, year, "PDF download failed after retries")

        time.sleep(1)

    # Extraction: do all years together so Excel has all years in one file
    all_pdf_paths = {}
    all_url_infos = {}
    conn_reports = get_pending_reports.__module__

    # Collect all downloaded-but-not-extracted reports for this company
    from database import get_conn
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM reports WHERE bse_code = ? AND status = 'downloaded'",
        (bse_code,)
    ).fetchall()
    conn.close()

    for row in rows:
        yr = row["fiscal_year"]
        path = Path(row["pdf_path"])
        if path.exists():
            all_pdf_paths[yr] = path
            all_url_infos[str(yr)] = {
                "pdf_url": row["pdf_url"],
                "bse_page": row["bse_page"],
            }

    if not all_pdf_paths:
        return downloaded, 0

    print(f"  Extracting {len(all_pdf_paths)} reports for {company_name}...")
    try:
        scheme_data, kmp_data = extract_all_years(company_name, all_pdf_paths, all_url_infos)
        output_path = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}" / "ESOP_data.xlsx"
        export_to_excel(company_name, scheme_data, kmp_data, sorted(all_pdf_paths.keys()), output_path)

        for yr in all_pdf_paths:
            mark_extracted(bse_code, yr, str(output_path))

        return downloaded, len(all_pdf_paths)

    except Exception as e:
        for yr in all_pdf_paths:
            mark_failed(bse_code, yr, str(e)[:300])
        print(f"  Extraction failed: {e}")
        return downloaded, 0


def run_update_cycle(companies: list[dict] = None) -> dict:
    """
    Full update cycle: check for new reports → download → extract.
    If companies is None, processes all companies in the DB.
    Returns summary stats.
    """
    init_db()

    if companies is None:
        companies = get_all_companies()

    if not companies:
        print("No companies tracked. Add companies first.")
        return {}

    total_new = 0
    total_downloaded = 0
    total_extracted = 0
    total_errors = 0

    print(f"\n{'='*60}")
    print(f"Update cycle started: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Companies to check: {len(companies)}")
    print(f"{'='*60}\n")

    for i, company in enumerate(companies, 1):
        bse_code = company["bse_code"]
        name = company["company_name"]
        print(f"\n[{i}/{len(companies)}] {name} ({bse_code})")

        try:
            new = check_new_reports(bse_code, name)
            total_new += new

            if new > 0:
                dl, ex = process_pending(bse_code, name)
                total_downloaded += dl
                total_extracted += ex

        except Exception as e:
            print(f"  Error processing {name}: {e}")
            total_errors += 1

        time.sleep(2)  # polite pause between companies

    summary = (
        f"Checked {len(companies)} companies | "
        f"New reports: {total_new} | "
        f"Downloaded: {total_downloaded} | "
        f"Extracted: {total_extracted} | "
        f"Errors: {total_errors}"
    )

    log_run(len(companies), total_new, total_extracted, total_errors, summary)

    print(f"\n{'='*60}")
    print(f"Cycle complete: {summary}")
    print(f"{'='*60}\n")

    return {
        "companies_checked": len(companies),
        "new_reports": total_new,
        "downloaded": total_downloaded,
        "extracted": total_extracted,
        "errors": total_errors,
    }

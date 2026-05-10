"""
Annual Report Agent - MVP
Usage:
    python main.py                          # interactive mode
    python main.py --fetch                  # fetch + download reports only
    python main.py --ask "your question"    # ask across all 5 years
    python main.py --debug                  # inspect BSE API response
"""
import argparse
import sys
from pathlib import Path

from config import DEFAULT_COMPANY
from bse_fetcher import get_annual_report_urls, list_all_filings_for_debug, save_url_map, load_url_map
from pdf_downloader import download_all, get_pdf_path
from agent import ask_multi_year, ask_comparative
from extractor import extract_all_years, export_to_excel


COMPANY = DEFAULT_COMPANY
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]


def fetch_and_download():
    print(f"\n{'='*60}")
    print(f"Company: {COMPANY['name']} (BSE: {COMPANY['bse_code']})")
    print(f"Years: {YEARS}")
    print(f"{'='*60}\n")

    print("Step 1: Fetching annual report URLs from BSE...")
    url_map = get_annual_report_urls(COMPANY["bse_code"], YEARS)

    if not url_map:
        print("\nNo annual reports found. Run with --debug to inspect BSE API response.")
        return {}

    save_url_map(COMPANY["bse_code"], url_map)
    print(f"\nStep 2: Downloading {len(url_map)} PDFs...")
    downloaded = download_all(COMPANY["name"], COMPANY["bse_code"], url_map)
    print(f"\nDownloaded {len(downloaded)}/{len(YEARS)} reports.")

    print("\nReport links saved:")
    for year, info in sorted(url_map.items()):
        print(f"  FY{year}: {info['pdf_url']}")
    return downloaded


def get_local_pdfs() -> dict[int, Path]:
    """Return already-downloaded PDFs without re-fetching."""
    pdfs = {}
    for year in YEARS:
        path = get_pdf_path(COMPANY["name"], COMPANY["bse_code"], year)
        if path.exists():
            pdfs[year] = path
    return pdfs


def interactive_mode(pdf_paths: dict[int, Path]):
    print(f"\n{'='*60}")
    print("Annual Report Q&A Agent")
    print(f"Company: {COMPANY['name']} | Years: {sorted(pdf_paths.keys())}")
    print("Type 'exit' to quit | Type 'compare' prefix for multi-year trend")
    print(f"{'='*60}\n")

    while True:
        question = input("Your question: ").strip()
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue

        comparative = question.lower().startswith("compare")

        if comparative:
            print("\nRunning comparative analysis across all years...\n")
            answer = ask_comparative(COMPANY["name"], pdf_paths, question)
            print(f"\nAnswer:\n{answer}\n")
        else:
            print("\nQuerying each year...\n")
            answers = ask_multi_year(COMPANY["name"], pdf_paths, question)
            print("\n" + "="*60)
            for year, ans in sorted(answers.items()):
                print(f"\nFY{year}:\n{ans}\n")
            print("="*60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="Fetch and download PDFs")
    parser.add_argument("--ask", type=str, help="Ask a question across all years")
    parser.add_argument("--compare", type=str, help="Ask a comparative question across years")
    parser.add_argument("--extract", action="store_true", help="Extract structured ESOP data and export to Excel")
    parser.add_argument("--debug", action="store_true", help="Debug BSE API response")
    args = parser.parse_args()

    if args.debug:
        print("BSE API response for FY2024:")
        import json
        data = list_all_filings_for_debug(COMPANY["bse_code"], 2024)
        print(json.dumps(data, indent=2)[:3000])
        return

    if args.fetch:
        fetch_and_download()
        return

    # Load existing PDFs or fetch if none exist
    pdf_paths = get_local_pdfs()
    if not pdf_paths:
        print("No local PDFs found. Fetching from BSE...")
        pdf_paths = fetch_and_download()

    if not pdf_paths:
        print("No reports available. Exiting.")
        sys.exit(1)

    if args.extract:
        url_map = load_url_map(COMPANY["bse_code"])
        print(f"\nExtracting structured ESOP data for {COMPANY['name']} ({len(pdf_paths)} years)...")
        scheme_data, kmp_data = extract_all_years(COMPANY["name"], pdf_paths, url_map)
        from config import DATA_DIR
        company_dir = DATA_DIR / f"{COMPANY['bse_code']}_{COMPANY['name'].replace(' ', '_')}"
        company_dir.mkdir(parents=True, exist_ok=True)
        output_path = company_dir / "ESOP_data.xlsx"
        export_to_excel(COMPANY["name"], scheme_data, kmp_data, sorted(pdf_paths.keys()), output_path)
        print(f"Done. Open: {output_path}")
        return

    if args.ask:
        url_map = load_url_map(COMPANY["bse_code"])
        answers = ask_multi_year(COMPANY["name"], pdf_paths, args.ask, url_map)
        for year, ans in sorted(answers.items()):
            print(f"\n{'='*60}\nFY{year}\n{'='*60}\n{ans}")
        return

    if args.compare:
        answer = ask_comparative(COMPANY["name"], pdf_paths, args.compare)
        print(f"\n{answer}")
        return

    # Default: interactive mode
    interactive_mode(pdf_paths)


if __name__ == "__main__":
    main()

import requests
import time
from pathlib import Path
from config import BSE_HEADERS, DATA_DIR


def get_pdf_path(company_name: str, bse_code: str, year: int) -> Path:
    company_dir = DATA_DIR / f"{bse_code}_{company_name.replace(' ', '_')}"
    company_dir.mkdir(parents=True, exist_ok=True)
    return company_dir / f"FY{year}.pdf"


def download_pdf(url: str, save_path: Path, retries: int = 3) -> bool:
    """Downloads PDF from BSE and saves to disk. Skips if already downloaded."""
    if save_path.exists() and save_path.stat().st_size > 10_000:
        print(f"  Already downloaded: {save_path.name}")
        return True

    for attempt in range(retries):
        try:
            print(f"  Downloading {save_path.name} (attempt {attempt + 1})...")
            resp = requests.get(url, headers=BSE_HEADERS, timeout=60, stream=True)
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower() and "octet-stream" not in content_type.lower():
                print(f"  Warning: unexpected content type: {content_type}")

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_mb = save_path.stat().st_size / 1_000_000
            print(f"  Downloaded: {save_path.name} ({size_mb:.1f} MB)")
            return True

        except Exception as e:
            print(f"  Attempt {attempt + 1} failed: {e}")
            time.sleep(2 * (attempt + 1))

    return False


def download_all(company_name: str, bse_code: str, url_map: dict) -> dict[int, Path]:
    """Downloads all annual report PDFs. Returns {year: local_path}."""
    downloaded = {}
    for year, info in url_map.items():
        year = int(year)
        url = info["pdf_url"] if isinstance(info, dict) else info
        path = get_pdf_path(company_name, bse_code, year)
        success = download_pdf(url, path)
        if success:
            downloaded[year] = path
    return downloaded

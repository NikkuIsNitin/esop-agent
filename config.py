import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
}

BSE_ANNEX_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"

# Test company: Infosys
DEFAULT_COMPANY = {
    "name": "Infosys",
    "bse_code": "500209",
}

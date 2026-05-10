"""
PDF text extraction with multiple fallback strategies.
Strategy order: PyMuPDF (fitz) → pdfplumber → pdfplumber with tolerances.
"""
from pathlib import Path

ESOP_KEYWORDS = [
    # Standard Indian ESOP terms
    "employee stock", "esop", "esos", "esrs", "stock option", "share-based",
    "share based", "restricted stock", "rsu", "stock appreciation",
    "equity settled", "options granted", "options vested", "options exercised",
    "black-scholes", "black scholes", "fair value of options",
    # Broader equity compensation terms
    "long-term incentive", "long term incentive", "lti plan",
    "equity incentive", "equity compensation", "equity award",
    "performance stock unit", "performance share unit", "psu",
    "restricted stock unit", "restricted share unit",
    "stock award", "share award", "equity plan",
    "deferred stock", "phantom stock", "employee equity",
    "stock-based compensation", "stock based compensation",
    "share-based payment", "share based payment",
    "employee benefit trust", "employee welfare trust",
    "employee stock ownership", "employees stock option",
    "employees stock ownership", "employee stock appreciation",
    "grant of options", "vesting schedule", "exercise price",
    # (regulation 34 removed — matches AGM cover letters under SEBI LODR, not ESOP sections)
]

PRIMARY_ESOP_SIGNALS = [
    "options granted", "options vested", "options exercised", "options lapsed",
    "black-scholes", "black scholes", "weighted average exercise price",
    "fair value of options", "expected volatility",
    "units granted", "units vested", "units forfeited",
    "rsus granted", "rsus vested", "rsus forfeited",
    "shares granted", "shares vested", "shares forfeited",
    "stock-based compensation expense", "share-based payment expense",
    "intrinsic value", "monte carlo", "binomial model",
]

MAX_PAGES_STANDARD  = 15   # first attempt
MAX_PAGES_EXPANDED  = 30   # second attempt (more pages)
MAX_CHARS_PER_PAGE  = 2000
MAX_TOTAL_CHARS     = 28000


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_with_fitz(pdf_path: Path) -> str:
    """Primary extractor — handles rotated pages, complex layouts, better than pdfplumber."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        pages_text = []
        for i, page in enumerate(doc):
            # fitz handles rotation internally
            text = page.get_text("text") or ""
            # Try block layout if plain text looks garbled (reversed chars)
            if text and _looks_garbled(text):
                text = page.get_text("blocks")
                if isinstance(text, list):
                    text = "\n".join(b[4] for b in text if isinstance(b[4], str))
            pages_text.append(f"[PAGE {i + 1}]\n{text}")
        doc.close()
        return "\n\n".join(pages_text)
    except Exception as e:
        print(f"    fitz extraction failed: {e}")
        return ""


def _extract_with_pdfplumber(pdf_path: Path) -> str:
    """Fallback extractor — pdfplumber standard mode."""
    try:
        import pdfplumber
        pages_text = []
        with pdfplumber.open(pdf_path) as pdf:
            total = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                # Try with tolerances if standard extraction looks poor
                if not text or _looks_garbled(text):
                    text = page.extract_text(x_tolerance=5, y_tolerance=5) or ""
                pages_text.append(f"[PAGE {i + 1}]\n{text}")
                if (i + 1) % 50 == 0:
                    print(f"    Parsed {i + 1}/{total} pages (pdfplumber)...")
        return "\n\n".join(pages_text)
    except Exception as e:
        print(f"    pdfplumber extraction failed: {e}")
        return ""


def _looks_garbled(text: str) -> bool:
    """Detect reversed/garbled text (common in rotated PDF pages)."""
    if not text or len(text) < 50:
        return False
    words = text.split()[:20]
    reversed_hits = sum(1 for w in words if len(w) > 3 and w[::-1].lower() in
                        {'ytic', 'erac', 'noitc', 'tneme', 'ytinu', 'latot', 'etad', 'srae', 'erorc'})
    return reversed_hits >= 3


def extract_text_from_pdf(pdf_path: Path) -> str:
    """
    Extract full text from PDF using multiple strategies.
    Tries PyMuPDF first (best for complex layouts), falls back to pdfplumber.
    Caches result to .txt file for reuse.
    """
    text_path = pdf_path.with_suffix(".txt")

    if text_path.exists():
        cached = text_path.read_text(encoding="utf-8")
        # Re-extract if cached text looks like it failed (very short or mostly garbled)
        useful_chars = sum(1 for c in cached if c.isalnum())
        if useful_chars > 5000:
            print(f"  Using cached text: {text_path.name}")
            return cached
        print(f"  Cached text appears poor — re-extracting...")
        text_path.unlink()

    print(f"  Extracting text from {pdf_path.name} ...")

    # Strategy 1: PyMuPDF
    full_text = _extract_with_fitz(pdf_path)

    # Strategy 2: pdfplumber fallback
    if not full_text or _text_quality(full_text) < 0.3:
        print(f"  fitz gave poor results, trying pdfplumber...")
        plumber_text = _extract_with_pdfplumber(pdf_path)
        if _text_quality(plumber_text) > _text_quality(full_text):
            full_text = plumber_text

    if full_text:
        text_path.write_text(full_text, encoding="utf-8")
        page_count = full_text.count("[PAGE ")
        print(f"  Extracted {page_count} pages → {text_path.name}")

    return full_text


def _text_quality(text: str) -> float:
    """0–1 quality score: fraction of alphanumeric chars in a text sample."""
    if not text:
        return 0.0
    sample = text[:5000]
    alnum = sum(1 for c in sample if c.isalnum())
    return alnum / max(len(sample), 1)


# ── ESOP section extraction ────────────────────────────────────────────────────

def _score_page(page_text: str) -> int:
    """Score page by ESOP keyword density."""
    text_lower = page_text.lower()
    score = sum(text_lower.count(kw) for kw in ESOP_KEYWORDS)
    score += sum(text_lower.count(sig) * 3 for sig in PRIMARY_ESOP_SIGNALS)
    return score


def extract_esop_section(full_text: str, max_pages: int = MAX_PAGES_STANDARD) -> tuple[str, list]:
    """
    Returns (esop_text, page_numbers) — the top-N ESOP-dense pages.
    max_pages controls how many pages to include (use more on retry attempts).
    """
    if not full_text:
        return "", []

    page_blocks = full_text.split("[PAGE ")
    scored_pages = []

    for block in page_blocks:
        if not block.strip():
            continue
        page_num = block.split("]")[0] if "]" in block else "?"
        score = _score_page(block)
        if score > 0:
            scored_pages.append((score, page_num, block))

    if not scored_pages:
        return "", []

    scored_pages.sort(key=lambda x: x[0], reverse=True)
    top_pages = scored_pages[:max_pages]
    top_pages.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0)

    page_nums = [p[1] for p in top_pages]
    print(f"  ESOP pages (top {max_pages}): {page_nums[:10]}{'...' if len(page_nums) > 10 else ''}")

    sections, total_chars = [], 0
    for score, page_num, block in top_pages:
        chunk = f"[PAGE {block[:MAX_CHARS_PER_PAGE]}"
        if total_chars + len(chunk) > MAX_TOTAL_CHARS:
            break
        sections.append(chunk)
        total_chars += len(chunk)

    result = "\n\n---\n\n".join(sections)
    print(f"  Sending {len(sections)} pages, {total_chars:,} chars to Claude")
    return result, page_nums


def get_esop_text(pdf_path: Path, max_pages: int = MAX_PAGES_STANDARD) -> tuple[str, list]:
    """Returns (esop_section_text, page_numbers). max_pages controls depth."""
    full_text = extract_text_from_pdf(pdf_path)
    return extract_esop_section(full_text, max_pages=max_pages)


def get_full_text(pdf_path: Path) -> str:
    """Return cached (or freshly extracted) full document text."""
    return extract_text_from_pdf(pdf_path)

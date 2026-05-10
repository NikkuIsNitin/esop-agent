import time
import anthropic
from pathlib import Path
from config import ANTHROPIC_API_KEY
from pdf_parser import get_esop_text

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def _call_claude_with_retry(kwargs: dict, retries: int = 4) -> anthropic.types.Message:
    for attempt in range(retries):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            wait = 60 * (attempt + 1)
            print(f"  Rate limit hit — waiting {wait}s before retry {attempt + 1}/{retries}...")
            time.sleep(wait)
    raise RuntimeError("Rate limit retries exhausted")

SYSTEM_PROMPT = """You are a financial analyst specializing in analyzing Indian company annual reports.

Your job is to answer questions strictly based on the annual report text provided to you.

Rules:
- Only use information present in the provided annual report text
- If a data point is not found, say "Not found in annual report FY{year}"
- Always cite the exact page number for every data point you extract (e.g. "Page 187")
- For ESOP data, extract exact numbers — options granted, vested, exercised, lapsed, exercise price, vesting schedule, fair value, Black-Scholes assumptions
- Never guess or use external knowledge
- If the PDF text is garbled or scanned, say so

At the end of your answer always include a "Sources" section in this exact format:
Sources:
- Annual Report FY{year} | Page <X>, <Y>, <Z> | <PDF direct link> | BSE Filing: <BSE page link>"""


def ask_single_year(
    company_name: str,
    year: int,
    pdf_path: Path,
    question: str,
    url_info: dict = None,
) -> str:
    """Ask a question about one year's annual report."""
    esop_text, pages = get_esop_text(pdf_path)

    if not esop_text:
        return f"No ESOP-related content found in {company_name} FY{year} annual report."

    pdf_url = url_info.get("pdf_url", "N/A") if url_info else "N/A"
    bse_page = url_info.get("bse_page", "N/A") if url_info else "N/A"

    print(f"  Sending FY{year} ESOP text to Claude ({len(esop_text)} chars, pages: {pages})...")

    response = _call_claude_with_retry(dict(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT.format(year=year),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Company: {company_name}\nFiscal Year: FY{year}\n"
                            f"PDF Link: {pdf_url}\nBSE Filing Page: {bse_page}\n\n"
                            f"Annual Report ESOP Section:\n\n{esop_text}"
                        ),
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"Question: {question}",
                    },
                ],
            }
        ],
    ))

    return response.content[0].text


def ask_multi_year(
    company_name: str,
    pdf_paths: dict[int, Path],
    question: str,
    url_map: dict = None,
) -> dict[int, str]:
    """Ask the same question across multiple years. Returns {year: answer}."""
    answers = {}
    for year, path in sorted(pdf_paths.items()):
        print(f"\nQuerying FY{year}...")
        url_info = (url_map or {}).get(str(year)) or (url_map or {}).get(year)
        answers[year] = ask_single_year(company_name, year, path, question, url_info)
    return answers


def ask_comparative(
    company_name: str,
    pdf_paths: dict[int, Path],
    question: str,
) -> str:
    """
    Asks Claude to compare data across all years in a single call.
    Useful for trend questions like 'How have grants changed over 5 years?'
    """
    year_texts = {}
    for year, path in sorted(pdf_paths.items()):
        esop_text, pages = get_esop_text(path)
        if esop_text:
            year_texts[year] = esop_text
        else:
            year_texts[year] = "No ESOP section found."

    combined = ""
    for year, text in sorted(year_texts.items()):
        combined += f"\n\n{'='*60}\nFY{year} ANNUAL REPORT - ESOP SECTION\n{'='*60}\n{text}"

    print(f"  Sending {len(year_texts)} years of data to Claude for comparison...")

    response = _call_claude_with_retry(dict(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT.format(year="(multiple years)"),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Company: {company_name}\nYears: {sorted(year_texts.keys())}\n\nAnnual Report Data (all years):\n{combined}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": f"Question: {question}\n\nPlease answer with a year-by-year breakdown and then a summary trend.",
                    },
                ],
            }
        ],
    ))

    return response.content[0].text

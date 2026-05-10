"""
ESOP extraction schema — exactly matches the reference Excel format from the images.
Row order matches CEINSYS / Wanbury / Almondz reference files.
"""

# ── Exact field order (matches image row structure) ───────────────────────────

SCHEME_FIELDS_ORDERED = [
    # ── Movement table ────────────────────────────────────────────────────────
    ("options_outstanding_beginning",  "Nos of Options Outstanding at the Beginning of the period"),
    ("options_granted",                "Option Granted during the Year"),
    ("pricing_formula",                "Pricing Formula"),
    ("options_vested",                 "Options Vested during the Year"),
    ("options_exercised",              "Options Exercised during the year"),
    ("shares_arising_from_exercise",   "Total nos shares arising as a result of exercise"),
    ("options_lapsed",                 "Options lapsed during the year"),
    ("options_forfeited",              "Options forfeited during the year"),
    ("money_realised_by_exercise_rs",  "Money Realised by Exercise of options during the year (Rs)"),
    ("options_outstanding_end",        "Options outstanding at the end of the year"),
    ("options_exercisable_end",        "Total nos of options exercisable at the end of the period"),
    # ── Blank row ─────────────────────────────────────────────────────────────
    (None, None),
    # ── Valuation ─────────────────────────────────────────────────────────────
    ("weighted_avg_exercise_price",    "Weighted average exercise price"),
    ("weighted_avg_fair_value",        "Weighted average fair value"),
    ("stock_price_end_of_year",        "Stock price at the end of the year"),
    # ── Blank rows ────────────────────────────────────────────────────────────
    (None, None),
    (None, None),
    # ── Wealth / Pool ─────────────────────────────────────────────────────────
    ("wealth_creation_pretax",         "Wealth Creation (Pre-tax)"),
    (None, None),
    ("pool_approved",                  "Pool Approved"),
    ("shares_issued_against_exercise", "Shares issued against Exercise"),
    ("pool_balance",                   "Pool Balance"),
    (None, None),
    ("sources_of_shares",              "Sources of shares"),
    # ── Blank row ─────────────────────────────────────────────────────────────
    (None, None),
    # ── Accounting & capital ──────────────────────────────────────────────────
    ("accounting_method",              "Accounting Method"),
    ("amortisation",                   "Amortisation"),
    (None, None),
    ("paid_up_capital",                "Paid up capital on 31st Mar (No. of shares)"),
    # ── KEY COMPUTED METRICS (highlighted in reference images) ────────────────
    ("dilution_pct",                   "% Dilution (Pool Approved / Paid-up Capital)"),
    ("ownership_pct",                  "% in Ownership (Options Outstanding / Paid-up Capital)"),
    ("overhang_pct",                   "% Option Overhang (Outstanding / Paid-up Capital)"),
    ("burn_rate_pct",                  "Burn Rate (Options Granted in FY / Paid-up Capital)"),
    # ── Additional info ───────────────────────────────────────────────────────
    ("esop_cost",                      "ESOP Cost / Expense for the Year (Rs)"),
    ("vesting_period",                 "Vesting Period"),
    ("additional_information",         "Additional Information"),
    # ── Source metadata ───────────────────────────────────────────────────────
    ("source_page",                    "Source Page(s) in Annual Report"),
    ("source_pdf_url",                 "Source PDF URL (BSE)"),
]

# Flat field list (excluding blank rows)
ESOP_FIELDS = [k for k, _ in SCHEME_FIELDS_ORDERED if k is not None]

# Label lookup
FIELD_LABELS = {k: v for k, v in SCHEME_FIELDS_ORDERED if k is not None}

# ── KMP sheet ─────────────────────────────────────────────────────────────────

KMP_FIELDS = [
    "fiscal_year", "document", "kmp_name", "designation",
    "options_granted", "options_vested", "options_exercised",
    "shares_arising_from_exercise", "exercise_price", "source_page",
]

KMP_FIELD_LABELS = {
    "fiscal_year":                 "Year",
    "document":                    "Document",
    "kmp_name":                    "KMP Name",
    "designation":                 "Designation",
    "options_granted":             "Options Granted",
    "options_vested":              "Options Vested",
    "options_exercised":           "Options Exercised",
    "shares_arising_from_exercise":"Total Shares Arising from Exercise",
    "exercise_price":              "Exercise Price (₹)",
    "source_page":                 "Source Page",
}

# ── Rows that get yellow highlight in Excel (matching reference images) ────────

HIGHLIGHT_ROWS = {
    "options_granted",
    "dilution_pct",
    "ownership_pct",
    "overhang_pct",
    "burn_rate_pct",
    "additional_information",
}

# ── Rows that are section dividers (bold blue background) ─────────────────────

SECTION_ROWS = {
    "options_outstanding_beginning": "Option Movement",
    "weighted_avg_exercise_price":   "Valuation",
    "wealth_creation_pretax":        "Wealth & Pool",
    "accounting_method":             "Accounting & Capital",
    "dilution_pct":                  "% Metrics (Key Ownership Indicators)",
    "esop_cost":                     "Cost & Additional Info",
    "source_page":                   "Source Reference",
}

# ── Extraction prompts ─────────────────────────────────────────────────────────

SCHEME_EXTRACTION_PROMPT = """You are extracting ESOP/ESOS/RSU scheme data from an Indian company annual report.

The company may have MULTIPLE schemes. Extract ALL schemes found individually — do NOT combine separate schemes.

━━ SCHEME NAMING RULES ━━
Use SHORT, CONSISTENT names that stay the same across years:
- If the scheme has "RSU" in name: use "<year> RSU" e.g. "2015 RSU"
- If the scheme has "ESOP" or "ESOS" in name: use "<year> ESOP" e.g. "2015 ESOP"
- If a scheme is called "Stock Incentive Compensation Plan" with RSU and ESOP sub-categories,
  split it into separate entries: "<year> RSU" and "<year> ESOP"
- Expanded/additional plans: use "<year> ESP" e.g. "2015 ESP"
- New RSU plan from 2019: use "2019 RSU"

━━ NUMBER FORMAT ━━
All numbers: plain integers or decimals, no commas, no ₹ symbol. Use null if not found.
Options counts must be WHOLE NUMBERS (e.g. 4500000, not 45.00 lakh).

━━ PAID UP CAPITAL — CRITICAL ━━
paid_up_capital = TOTAL NUMBER OF EQUITY SHARES outstanding (NOT the rupee/crore amount).
Look for text like:
  "total number of equity shares" / "number of equity shares outstanding"
  "equity shares of face value" / "paid up equity shares"
If the annual report states the ESOP pool as a percentage of total shares, use that to back-calculate:
  total_shares = pool_approved / (pool_pct / 100)
Return paid_up_capital as a whole number (e.g. 4234000000 for 423.4 crore shares).
DO NOT return rupee/crore value — only the share COUNT.

━━ PERCENT FIELDS ━━
Compute these as plain decimals (0.05 means 5%):
- dilution_pct = pool_approved / paid_up_capital
- ownership_pct = options_outstanding_end / paid_up_capital
- overhang_pct = options_outstanding_end / paid_up_capital  (same as ownership_pct)
- burn_rate_pct = options_granted_this_fy / paid_up_capital
If the annual report states these % directly, use those values.

━━ JSON OUTPUT ━━
Return JSON array — one object per scheme:
[
  {{
    "scheme_name": "<short consistent name e.g. 2015 RSU>",
    "options_outstanding_beginning": <number or null>,
    "options_granted": <number or null>,
    "pricing_formula": "<text or null>",
    "options_vested": <number or null>,
    "options_exercised": <number or null>,
    "shares_arising_from_exercise": <number or null>,
    "options_lapsed": <number or null>,
    "options_forfeited": <number or null>,
    "money_realised_by_exercise_rs": <number or null>,
    "options_outstanding_end": <number or null>,
    "options_exercisable_end": <number or null>,
    "weighted_avg_exercise_price": <number or null>,
    "weighted_avg_fair_value": <number or null>,
    "stock_price_end_of_year": <number or null>,
    "wealth_creation_pretax": <number or null>,
    "pool_approved": <number or null>,
    "shares_issued_against_exercise": <number or null>,
    "pool_balance": <number or null>,
    "sources_of_shares": "<Fresh Issue / Secondary / Primary or null>",
    "accounting_method": "<Fair Value / Intrinsic Value or null>",
    "amortisation": "<text or null>",
    "paid_up_capital": <SHARE COUNT as whole number, e.g. 4234000000, or null>,
    "dilution_pct": <decimal e.g. 0.0588 or null>,
    "ownership_pct": <decimal or null>,
    "overhang_pct": <decimal or null>,
    "burn_rate_pct": <decimal or null>,
    "esop_cost": <number or null>,
    "vesting_period": "<text or null>",
    "additional_information": "<key facts: pool size, max per employee, expiry etc. or null>",
    "source_page": "<page numbers>"
  }}
]

Company: {company}
Fiscal Year: FY{year}
PDF Link: {pdf_url}

Annual Report ESOP Section:
{esop_text}

Return ONLY valid JSON array. No markdown, no explanation."""


KMP_EXTRACTION_PROMPT = """Extract KMP (Key Managerial Personnel) individual ESOP grant data from this Indian company annual report.

Find ALL named individuals who received stock options/RSUs.
Return JSON array — one object per KMP:
[
  {{
    "kmp_name": "Full name",
    "designation": "Role e.g. CFO, CEO, MD",
    "options_granted": <number or null>,
    "options_vested": <number or null>,
    "options_exercised": <number or null>,
    "shares_arising_from_exercise": <number or null>,
    "exercise_price": <number or null>,
    "source_page": "<page numbers>"
  }}
]

If no individual KMP data found, return: []

Company: {company}
Fiscal Year: FY{year}
Document: {pdf_url}

Annual Report ESOP Section:
{esop_text}

Return ONLY valid JSON array."""

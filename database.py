"""
SQLite database for tracking companies, downloaded reports, and extraction status.
This is what lets the agent run incrementally — only processing what's new.
"""
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "esop_agent.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            bse_code        TEXT PRIMARY KEY,
            company_name    TEXT NOT NULL,
            added_at        TEXT DEFAULT (datetime('now')),
            last_checked    TEXT
        );

        CREATE TABLE IF NOT EXISTS reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            bse_code        TEXT NOT NULL,
            fiscal_year     INTEGER NOT NULL,
            pdf_url         TEXT,
            bse_page        TEXT,
            headline        TEXT,
            pdf_path        TEXT,
            downloaded_at   TEXT,
            extracted_at    TEXT,
            excel_path      TEXT,
            status          TEXT DEFAULT 'pending',
            error_msg       TEXT,
            UNIQUE(bse_code, fiscal_year),
            FOREIGN KEY (bse_code) REFERENCES companies(bse_code)
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at          TEXT DEFAULT (datetime('now')),
            companies_checked INTEGER DEFAULT 0,
            new_reports_found INTEGER DEFAULT 0,
            extractions_done  INTEGER DEFAULT 0,
            errors            INTEGER DEFAULT 0,
            summary           TEXT
        );
    """)
    conn.commit()
    conn.close()
    print(f"Database ready: {DB_PATH}")


# ── Company management ────────────────────────────────────────────────────────

def add_company(bse_code: str, company_name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO companies (bse_code, company_name) VALUES (?, ?)",
        (bse_code, company_name)
    )
    conn.commit()
    conn.close()


def get_all_companies() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM companies ORDER BY company_name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_last_checked(bse_code: str):
    conn = get_conn()
    conn.execute(
        "UPDATE companies SET last_checked = datetime('now') WHERE bse_code = ?",
        (bse_code,)
    )
    conn.commit()
    conn.close()


# ── Report tracking ───────────────────────────────────────────────────────────

def is_report_known(bse_code: str, fiscal_year: int) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM reports WHERE bse_code = ? AND fiscal_year = ?",
        (bse_code, fiscal_year)
    ).fetchone()
    conn.close()
    return row is not None


def upsert_report(bse_code: str, fiscal_year: int, url_info: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO reports (bse_code, fiscal_year, pdf_url, bse_page, headline, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        ON CONFLICT(bse_code, fiscal_year) DO UPDATE SET
            pdf_url  = excluded.pdf_url,
            bse_page = excluded.bse_page,
            headline = excluded.headline
    """, (
        bse_code, fiscal_year,
        url_info.get("pdf_url"), url_info.get("bse_page"), url_info.get("headline", "")[:200]
    ))
    conn.commit()
    conn.close()


def mark_downloaded(bse_code: str, fiscal_year: int, pdf_path: str):
    conn = get_conn()
    conn.execute("""
        UPDATE reports SET pdf_path = ?, downloaded_at = datetime('now'), status = 'downloaded'
        WHERE bse_code = ? AND fiscal_year = ?
    """, (pdf_path, bse_code, fiscal_year))
    conn.commit()
    conn.close()


def mark_extracted(bse_code: str, fiscal_year: int, excel_path: str):
    conn = get_conn()
    conn.execute("""
        UPDATE reports SET excel_path = ?, extracted_at = datetime('now'), status = 'done'
        WHERE bse_code = ? AND fiscal_year = ?
    """, (excel_path, bse_code, fiscal_year))
    conn.commit()
    conn.close()


def mark_failed(bse_code: str, fiscal_year: int, error: str):
    conn = get_conn()
    conn.execute("""
        UPDATE reports SET status = 'failed', error_msg = ?
        WHERE bse_code = ? AND fiscal_year = ?
    """, (error[:500], bse_code, fiscal_year))
    conn.commit()
    conn.close()


def get_pending_reports(bse_code: str = None) -> list[dict]:
    conn = get_conn()
    if bse_code:
        rows = conn.execute(
            "SELECT * FROM reports WHERE bse_code = ? AND status IN ('pending','failed')",
            (bse_code,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM reports WHERE status IN ('pending','failed')"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    conn = get_conn()
    stats = {
        "companies":  conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "total":      conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
        "done":       conn.execute("SELECT COUNT(*) FROM reports WHERE status='done'").fetchone()[0],
        "pending":    conn.execute("SELECT COUNT(*) FROM reports WHERE status='pending'").fetchone()[0],
        "failed":     conn.execute("SELECT COUNT(*) FROM reports WHERE status='failed'").fetchone()[0],
        "downloaded": conn.execute("SELECT COUNT(*) FROM reports WHERE status='downloaded'").fetchone()[0],
    }
    conn.close()
    return stats


def log_run(companies_checked: int, new_reports: int, extractions: int, errors: int, summary: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO run_log (companies_checked, new_reports_found, extractions_done, errors, summary)
        VALUES (?, ?, ?, ?, ?)
    """, (companies_checked, new_reports, extractions, errors, summary))
    conn.commit()
    conn.close()


def get_recent_runs(n: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM run_log ORDER BY run_at DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print("Stats:", get_stats())

"""
Scheduler — runs the update agent automatically.

Schedule logic:
  - Filing season (April–September): check weekly (new annual reports filed)
  - Off season (October–March):      check monthly (unlikely to find new reports)

Run modes:
  python scheduler.py              → start daemon (runs forever)
  python scheduler.py --now        → run one update cycle immediately
  python scheduler.py --add        → add a company to track
  python scheduler.py --list       → list tracked companies and stats
  python scheduler.py --status     → show DB stats and recent runs
"""
import argparse
import time
import schedule
from datetime import date, datetime

from database import (
    init_db, add_company, get_all_companies,
    get_stats, get_recent_runs,
)
from updater import run_update_cycle


def is_filing_season() -> bool:
    """April–September is when Indian companies file annual reports."""
    return date.today().month in (4, 5, 6, 7, 8, 9)


def setup_schedule():
    """
    Weekly in filing season, monthly in off-season.
    Runs at 8:00 AM to avoid overloading BSE API during market hours.
    """
    if is_filing_season():
        schedule.every().monday.at("08:00").do(run_update_cycle)
        print("Filing season — scheduled weekly (every Monday 08:00)")
    else:
        schedule.every(30).days.do(run_update_cycle)
        print("Off season — scheduled monthly (every 30 days)")


def start_daemon():
    init_db()
    companies = get_all_companies()
    if not companies:
        print("No companies tracked yet. Add some with: python scheduler.py --add")
        return

    print(f"\nAgent starting. Tracking {len(companies)} companies.")
    print("Companies:")
    for c in companies:
        print(f"  {c['bse_code']} — {c['company_name']}")

    setup_schedule()

    # Run immediately on start, then follow schedule
    print("\nRunning initial update cycle...")
    run_update_cycle()

    print("\nEntering scheduled mode. Press Ctrl+C to stop.\n")
    while True:
        schedule.run_pending()
        next_run = schedule.next_run()
        if next_run:
            delta = next_run - datetime.now()
            hours = int(delta.total_seconds() / 3600)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
                  f"Waiting... next run in ~{hours}h", end="\r")
        time.sleep(60)


def cmd_add():
    print("Add a company to track")
    bse_code = input("BSE Code (e.g. 500209): ").strip()
    name = input("Company Name (e.g. Infosys): ").strip()
    if bse_code and name:
        init_db()
        add_company(bse_code, name)
        print(f"Added: {name} ({bse_code})")
    else:
        print("Cancelled — both BSE code and name required.")


def cmd_list():
    init_db()
    companies = get_all_companies()
    if not companies:
        print("No companies tracked yet.")
        return
    print(f"\nTracked companies ({len(companies)}):")
    for c in companies:
        checked = c.get("last_checked", "never")
        print(f"  {c['bse_code']:<10} {c['company_name']:<30} last checked: {checked or 'never'}")


def cmd_status():
    init_db()
    stats = get_stats()
    print("\nDatabase Stats:")
    print(f"  Companies tracked : {stats['companies']}")
    print(f"  Total reports     : {stats['total']}")
    print(f"  Done (extracted)  : {stats['done']}")
    print(f"  Downloaded        : {stats['downloaded']}")
    print(f"  Pending           : {stats['pending']}")
    print(f"  Failed            : {stats['failed']}")

    runs = get_recent_runs(5)
    if runs:
        print("\nRecent runs:")
        for r in runs:
            print(f"  {r['run_at'][:16]} | {r['summary']}")


def main():
    parser = argparse.ArgumentParser(description="ESOP Update Agent Scheduler")
    parser.add_argument("--now",    action="store_true", help="Run one update cycle now")
    parser.add_argument("--add",    action="store_true", help="Add a company to track")
    parser.add_argument("--list",   action="store_true", help="List tracked companies")
    parser.add_argument("--status", action="store_true", help="Show DB stats and recent runs")
    args = parser.parse_args()

    if args.add:
        cmd_add()
    elif args.list:
        cmd_list()
    elif args.status:
        cmd_status()
    elif args.now:
        init_db()
        run_update_cycle()
    else:
        start_daemon()


if __name__ == "__main__":
    main()

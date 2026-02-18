"""
JobHunter — Windows Scheduled Task setup.

Creates (or removes) a Windows Task Scheduler entry that runs the
scraper pipeline daily without requiring an open terminal.

Usage:
    python scripts/setup_windows_task.py              # create, daily at 08:00
    python scripts/setup_windows_task.py --time 19:00 # custom time
    python scripts/setup_windows_task.py --delete     # remove the task

Requirements:
    - Windows only (uses schtasks.exe)
    - No administrator rights required for user-level tasks
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TASK_NAME      = "JobHunterScraper"
PROJECT_ROOT   = Path(__file__).resolve().parent.parent
SCRAPER_SCRIPT = PROJECT_ROOT / "scripts" / "run_scrapers.py"
PYTHON         = sys.executable


def _schtasks(*args, check=False):
    """Run schtasks with the given arguments; return CompletedProcess."""
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        check=check,
    )


def task_exists() -> bool:
    """Return True if the scheduled task already exists."""
    r = _schtasks("/Query", "/TN", TASK_NAME)
    return r.returncode == 0


def create_task(run_time: str) -> None:
    """Create (or overwrite) the Windows Scheduled Task."""
    # schtasks /TR requires the full command as a quoted string
    task_run = f'"{PYTHON}" "{SCRAPER_SCRIPT}"'

    print("=" * 60)
    print(f"JobHunter — Creating Windows Scheduled Task")
    print("=" * 60)
    print(f"  Task name : {TASK_NAME}")
    print(f"  Python    : {PYTHON}")
    print(f"  Script    : {SCRAPER_SCRIPT}")
    print(f"  Schedule  : daily at {run_time}")
    print()

    # Verify the scraper script exists before registering
    if not SCRAPER_SCRIPT.exists():
        print(f"[ERROR] Scraper script not found: {SCRAPER_SCRIPT}")
        sys.exit(1)

    r = _schtasks(
        "/Create",
        "/TN", TASK_NAME,
        "/TR", task_run,
        "/SC", "DAILY",
        "/ST", run_time,
        "/F",               # force-overwrite if already exists
    )

    if r.returncode == 0:
        print(f"[OK] Task '{TASK_NAME}' created successfully.")
        print()
        print("Verify with:")
        print(f"    schtasks /Query /TN {TASK_NAME} /FO LIST /V")
        print()
        print("Run immediately with:")
        print(f"    schtasks /Run /TN {TASK_NAME}")
    else:
        print(f"[ERROR] schtasks failed (exit code {r.returncode}).")
        if r.stdout.strip():
            print(f"  stdout: {r.stdout.strip()}")
        if r.stderr.strip():
            print(f"  stderr: {r.stderr.strip()}")
        print()
        print("Troubleshooting tips:")
        print("  - Try running this script from an elevated (Admin) terminal.")
        print("  - Make sure schtasks.exe is available (it should be on all Windows).")
        sys.exit(1)


def delete_task() -> None:
    """Remove the scheduled task."""
    if not task_exists():
        print(f"[INFO] Task '{TASK_NAME}' does not exist — nothing to delete.")
        return

    r = _schtasks("/Delete", "/TN", TASK_NAME, "/F")
    if r.returncode == 0:
        print(f"[OK] Task '{TASK_NAME}' deleted.")
    else:
        print(f"[ERROR] Could not delete task: {r.stderr.strip()}")
        sys.exit(1)


def main() -> None:
    if sys.platform != "win32":
        print("[ERROR] This script is Windows-only.")
        print("        Use cron (crontab -e) on Linux/macOS instead.")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Set up a Windows Scheduled Task for the JobHunter scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--time",
        default="08:00",
        metavar="HH:MM",
        help="Daily run time in HH:MM format (default: 08:00)",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Remove the scheduled task instead of creating it",
    )
    args = parser.parse_args()

    if args.delete:
        delete_task()
        return

    # Validate time format
    try:
        datetime.strptime(args.time, "%H:%M")
    except ValueError:
        print(f"[ERROR] Invalid --time value '{args.time}'. Use HH:MM (e.g. 08:00).")
        sys.exit(1)

    if task_exists():
        print(f"[INFO] Task '{TASK_NAME}' already exists — will overwrite.")

    create_task(args.time)


if __name__ == "__main__":
    main()

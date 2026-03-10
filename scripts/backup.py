"""
backup.py — Daily SQLite backup for JobHunter.

Usage:
    python scripts/backup.py

Copies data/jobhunter.db to BACKUP_DIR with a timestamped name, then
removes old backups keeping only the N most recent files.

Cron example (runs every night at 02:00):
    0 2 * * * cd /home/ubuntu/JobHunter && /home/ubuntu/JobHunter/venv/bin/python scripts/backup.py
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

# Absolute path of the database to back up
REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "jobhunter.db"

# Destination directory (created if it does not exist)
_default_backup = str(REPO_ROOT / "backups") if sys.platform == "win32" else "/home/ubuntu/backups"
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", _default_backup))

# Number of recent backups to keep (older ones are deleted)
KEEP_LAST = 7


# ── Main logic ───────────────────────────────────────────────────────────────

def main() -> int:
    # Verify source exists
    if not DB_PATH.exists():
        print(f"[backup] ERROR: database not found at {DB_PATH}", file=sys.stderr)
        return 1

    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Build destination filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"jobhunter_{timestamp}.db"

    # Use SQLite's backup API for a consistent copy (safe even during writes)
    src_conn = sqlite3.connect(str(DB_PATH))
    dst_conn = sqlite3.connect(str(dest))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    print(f"[backup] Backup created: {dest}")

    # Purge old backups — keep the KEEP_LAST most recent
    backups = sorted(
        BACKUP_DIR.glob("jobhunter_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[KEEP_LAST:]:
        old.unlink()
        print(f"[backup] Deleted old backup: {old.name}")

    remaining = min(len(backups), KEEP_LAST)
    print(f"[backup] Done. {remaining} backup(s) retained in {BACKUP_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

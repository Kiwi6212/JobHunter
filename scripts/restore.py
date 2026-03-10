"""
restore.py — Restore a JobHunter SQLite backup.

Usage:
    python scripts/restore.py <backup_file>

    <backup_file>   Path to the .db backup file to restore
                    (e.g. /home/ubuntu/backups/jobhunter_20260308_020000.db)

The live database (data/jobhunter.db) will be overwritten after explicit
confirmation. A safety copy of the current database is created alongside it
before the restore takes place.
"""

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── Configuration ────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "data" / "jobhunter.db"


# ── Main logic ───────────────────────────────────────────────────────────────

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/restore.py <backup_file>", file=sys.stderr)
        return 2

    backup_path = Path(sys.argv[1]).resolve()

    if not backup_path.exists():
        print(f"[restore] ERROR: backup file not found: {backup_path}", file=sys.stderr)
        return 1

    if not backup_path.is_file():
        print(f"[restore] ERROR: {backup_path} is not a file.", file=sys.stderr)
        return 1

    # Validate that the backup is a valid SQLite database
    try:
        conn = sqlite3.connect(str(backup_path))
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()
    except sqlite3.DatabaseError:
        print(f"[restore] ERROR: {backup_path} is not a valid SQLite database.", file=sys.stderr)
        return 1

    # Show what will happen and ask for confirmation
    print(f"[restore] Source  : {backup_path}")
    print(f"[restore] Target  : {DB_PATH}")

    if DB_PATH.exists():
        print(f"[restore] WARNING : the current database will be overwritten.")
    else:
        print(f"[restore] INFO    : no existing database at target path.")

    answer = input("[restore] Type YES to confirm: ").strip()
    if answer != "YES":
        print("[restore] Aborted.")
        return 0

    # Create a pre-restore safety copy of the current database
    if DB_PATH.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_copy = DB_PATH.with_name(f"jobhunter_pre_restore_{timestamp}.db")
        shutil.copy2(DB_PATH, safety_copy)
        print(f"[restore] Safety copy saved: {safety_copy}")

    # Ensure data/ directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Perform the restore
    shutil.copy2(backup_path, DB_PATH)
    print(f"[restore] Restore complete: {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

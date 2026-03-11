"""
Cleanup inactive user accounts for JobHunter.
Deletes non-admin user accounts that have been inactive for more than 90 days:
  - last_login older than 90 days, OR
  - never logged in (last_login is NULL) and created_at older than 90 days.

Removes all associated data: user_offers, password_resets, email_confirmations,
and uploaded documents in data/documents/{user_id}/.

Usage:
    python scripts/cleanup_inactive_users.py

Recommended cron (1st of each month at 04:00 UTC):
    0 4 1 * * cd /home/ubuntu/JobHunter && /home/ubuntu/JobHunter/venv/bin/python scripts/cleanup_inactive_users.py >> /home/ubuntu/logs/cleanup_users.log 2>&1
"""

import shutil
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import or_, and_

from app.database import SessionLocal, init_db
from app.models import User, UserOffer, PasswordReset, EmailConfirmation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("cleanup_inactive_users")

INACTIVE_DAYS = 90
DATA_DIR = project_root / "data"


def cleanup_inactive_users():
    """Find and delete user accounts inactive for more than INACTIVE_DAYS days."""
    init_db()
    db = SessionLocal()

    cutoff = datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)
    # SQLite stores naive datetimes, compare with naive cutoff too
    cutoff_naive = cutoff.replace(tzinfo=None)

    try:
        inactive_users = db.query(User).filter(
            User.role != "admin",
            or_(
                # Last login older than 90 days
                and_(User.last_login.isnot(None), User.last_login < cutoff_naive),
                # Never logged in and account created > 90 days ago
                and_(User.last_login.is_(None), User.created_at < cutoff_naive),
            ),
        ).all()

        if not inactive_users:
            log.info("No inactive users found (cutoff: %s). Nothing to do.", cutoff_naive.date())
            return

        log.info("Found %d inactive user(s) to delete (cutoff: %s).", len(inactive_users), cutoff_naive.date())

        for user in inactive_users:
            uid = user.id
            uname = user.username
            last = user.last_login.strftime("%Y-%m-%d") if user.last_login else "never"
            created = user.created_at.strftime("%Y-%m-%d") if user.created_at else "?"

            # Delete related rows
            n_uo = db.query(UserOffer).filter(UserOffer.user_id == uid).delete()
            n_pr = db.query(PasswordReset).filter(PasswordReset.user_id == uid).delete()
            n_ec = db.query(EmailConfirmation).filter(EmailConfirmation.user_id == uid).delete()

            # Delete uploaded documents
            docs_dir = DATA_DIR / "documents" / str(uid)
            docs_removed = False
            if docs_dir.exists():
                shutil.rmtree(docs_dir, ignore_errors=True)
                docs_removed = True

            # Delete user
            db.delete(user)
            db.commit()

            log.info(
                "DELETED user=%s (id=%d) | created=%s last_login=%s | "
                "removed: %d user_offers, %d password_resets, %d email_confirmations, docs=%s",
                uname, uid, created, last,
                n_uo, n_pr, n_ec, docs_removed,
            )

        log.info("Cleanup complete. %d account(s) deleted.", len(inactive_users))

    except Exception:
        db.rollback()
        log.exception("Error during cleanup — rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_inactive_users()

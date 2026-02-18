"""
JobHunter Scheduler — runs the scraper pipeline on a daily schedule.

Uses the lightweight `schedule` library to trigger run_scrapers.py
as a subprocess, capturing all output into logs/scheduler.log.

Usage:
    python scripts/scheduler.py                  # run every day at 19:00
    python scripts/scheduler.py --time 08:30     # custom time
    python scripts/scheduler.py --now            # run immediately, then schedule
    python scripts/scheduler.py --now --time 20:00
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

# ── Paths ───────────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
LOGS_DIR      = PROJECT_ROOT / "logs"
LOG_FILE      = LOGS_DIR / "scheduler.log"
SCRAPER_SCRIPT = PROJECT_ROOT / "scripts" / "run_scrapers.py"
PYTHON        = sys.executable

# ── Logging ─────────────────────────────────────────────────────────────────
LOGS_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("jobhunter.scheduler")
logger.setLevel(logging.INFO)

_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)
logger.addHandler(_ch)

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)


# ── Pipeline runner ──────────────────────────────────────────────────────────

def run_pipeline():
    """Execute run_scrapers.py as a subprocess and stream output to the log."""
    logger.info("=" * 60)
    logger.info("Starting scraper pipeline")
    logger.info("=" * 60)

    start = datetime.now()
    try:
        result = subprocess.run(
            [PYTHON, str(SCRAPER_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=3600,          # kill after 1 hour
        )
        duration = (datetime.now() - start).total_seconds()

        # Log stdout line-by-line
        for line in (result.stdout or "").splitlines():
            if line.strip():
                logger.info("[scrapers] %s", line)

        # Log stderr as warnings (includes Python logging output)
        for line in (result.stderr or "").splitlines():
            if line.strip():
                logger.warning("[scrapers:err] %s", line)

        if result.returncode == 0:
            logger.info("Pipeline completed successfully in %.0fs", duration)
        else:
            logger.error(
                "Pipeline exited with code %d after %.0fs",
                result.returncode, duration,
            )

    except subprocess.TimeoutExpired:
        logger.error("Pipeline timed out after 1 hour — process killed")
    except Exception as exc:
        logger.error("Failed to launch pipeline: %s", exc, exc_info=True)

    # Always show next scheduled run after finishing
    nxt = schedule.next_run()
    if nxt:
        logger.info("Next run scheduled at: %s", nxt.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("-" * 60)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="JobHunter automatic scraper scheduler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--time",
        default="19:00",
        metavar="HH:MM",
        help="Daily execution time in HH:MM format (default: 19:00)",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="Run the pipeline immediately on startup, then continue on schedule",
    )
    args = parser.parse_args()

    # Validate --time format
    try:
        datetime.strptime(args.time, "%H:%M")
    except ValueError:
        print(f"[ERROR] Invalid --time value '{args.time}'. Use HH:MM (e.g. 19:00)")
        sys.exit(1)

    # Verify the scraper script exists
    if not SCRAPER_SCRIPT.exists():
        print(f"[ERROR] Scraper script not found: {SCRAPER_SCRIPT}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("JobHunter Scheduler starting")
    logger.info("  Python  : %s", PYTHON)
    logger.info("  Script  : %s", SCRAPER_SCRIPT)
    logger.info("  Log     : %s", LOG_FILE)
    logger.info("  Schedule: every day at %s", args.time)
    logger.info("=" * 60)

    # Register daily job
    schedule.every().day.at(args.time).do(run_pipeline)

    if args.now:
        logger.info("--now flag set: running pipeline immediately")
        run_pipeline()
    else:
        nxt = schedule.next_run()
        if nxt:
            logger.info(
                "Next run scheduled at: %s",
                nxt.strftime("%Y-%m-%d %H:%M:%S"),
            )

    logger.info("Scheduler running — press Ctrl+C to stop")

    try:
        while True:
            schedule.run_pending()
            time.sleep(30)          # check every 30 seconds
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user (KeyboardInterrupt)")


if __name__ == "__main__":
    main()

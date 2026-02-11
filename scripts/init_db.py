"""
Database initialization script for JobHunter.
Run this script to create the SQLite database and all required tables.

Usage:
    python scripts/init_db.py [--reset]

Options:
    --reset     Drop all existing tables and recreate them (⚠️ deletes all data!)
"""

import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.database import init_db, reset_db
from config import Config


def main():
    """Main entry point for database initialization."""
    print("=" * 60)
    print("JobHunter - Database Initialization")
    print("=" * 60)
    print()

    # Check for --reset flag
    reset_flag = "--reset" in sys.argv

    if reset_flag:
        print("⚠️  WARNING: --reset flag detected!")
        print("⚠️  This will delete ALL existing data in the database.")
        response = input("Are you sure you want to continue? (yes/no): ").strip().lower()

        if response != "yes":
            print("❌ Operation cancelled")
            return

        print()
        reset_db()
    else:
        init_db()

    print()
    print("=" * 60)
    print(f"Database ready at: {Config.DATABASE_PATH}")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Copy .env.example to .env and configure your API keys")
    print("  2. Run scrapers: python scripts/run_scrapers.py")
    print("  3. Launch dashboard: python -m flask run")
    print()


if __name__ == "__main__":
    main()

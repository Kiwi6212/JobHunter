"""
Database connection and session management for JobHunter.
Handles SQLite database initialization and provides session factory.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, scoped_session
from app.models import Base

# Get database path from config
from config import Config

# Ensure data directory exists
DATA_DIR = Path(Config.DATABASE_PATH).parent
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Create SQLite engine
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    echo=False,
    connect_args={"check_same_thread": False},
)

# Session factory
SessionLocal = scoped_session(sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
))


def init_db():
    """
    Initialize the database by creating all tables defined in models.
    Should be called once when setting up the application.
    """
    print("Initializing database...")
    print(f"Database location: {Config.DATABASE_PATH}")

    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Auto-migrate: add missing columns to existing tables
    _migrate_columns()

    print("[OK] Database initialized successfully!")
    print(f"[OK] Tables created: {', '.join(Base.metadata.tables.keys())}")


def _migrate_columns():
    """Add missing columns to existing tables and backfill data."""
    insp = inspect(engine)
    if "offers" not in insp.get_table_names():
        return

    existing = [c["name"] for c in insp.get_columns("offers")]

    if "offer_type" not in existing:
        print("[MIGRATE] Adding offer_type column to offers table...")
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE offers ADD COLUMN offer_type VARCHAR(20) NOT NULL DEFAULT 'job'"
            ))
            conn.execute(text(
                "UPDATE offers SET offer_type = 'recruiter' "
                "WHERE external_id LIKE 'lba_recruiter_%'"
            ))
        print("[MIGRATE] Done. Backfilled recruiter tags from external_id.")

    # Fix company names that are actually descriptions (> 50 chars of prose)
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE offers SET company = 'Non renseigné' "
            "WHERE length(company) > 50"
        ))
        if result.rowcount > 0:
            print(f"[MIGRATE] Fixed {result.rowcount} offers with description as company name.")


def get_db():
    """
    Dependency function to get database session.
    Yields a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def drop_all_tables():
    """
    Drop all tables from the database.
    WARNING: This will delete all data! Use only for development/testing.
    """
    print("[!] Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("[OK] All tables dropped")


def reset_db():
    """
    Reset the database by dropping and recreating all tables.
    WARNING: This will delete all data! Use only for development/testing.
    """
    print("[!] Resetting database...")
    drop_all_tables()
    init_db()
    print("[OK] Database reset complete")

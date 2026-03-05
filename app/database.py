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

    if "cv_match_score" not in existing:
        print("[MIGRATE] Adding cv_match_score column to offers table...")
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE offers ADD COLUMN cv_match_score FLOAT"
            ))
        print("[MIGRATE] Done.")

    if "domain_id" not in existing:
        print("[MIGRATE] Adding domain_id column to offers table...")
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE offers ADD COLUMN domain_id INTEGER REFERENCES domains(id)"
            ))
        print("[MIGRATE] Done.")

    # Migrate users table
    if "users" in insp.get_table_names():
        user_cols = [c["name"] for c in insp.get_columns("users")]
        if "is_active" not in user_cols:
            print("[MIGRATE] Adding is_active column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"
                ))
            print("[MIGRATE] Done.")
        if "totp_secret" not in user_cols:
            print("[MIGRATE] Adding totp_secret column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN totp_secret VARCHAR(64)"
                ))
            print("[MIGRATE] Done.")
        if "totp_enabled" not in user_cols:
            print("[MIGRATE] Adding totp_enabled column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN NOT NULL DEFAULT 0"
                ))
            print("[MIGRATE] Done.")
        if "security_question" not in user_cols:
            print("[MIGRATE] Adding security_question column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN security_question VARCHAR(255)"
                ))
            print("[MIGRATE] Done.")
        if "security_answer_hash" not in user_cols:
            print("[MIGRATE] Adding security_answer_hash column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN security_answer_hash VARCHAR(255)"
                ))
            print("[MIGRATE] Done.")
        if "email" not in user_cols:
            print("[MIGRATE] Adding email column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN email VARCHAR(255)"
                ))
            print("[MIGRATE] Done.")
        if "last_login" not in user_cols:
            print("[MIGRATE] Adding last_login column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN last_login DATETIME"
                ))
            print("[MIGRATE] Done.")
        if "claude_tokens_used" not in user_cols:
            print("[MIGRATE] Adding claude_tokens_used column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN claude_tokens_used INTEGER NOT NULL DEFAULT 0"
                ))
            print("[MIGRATE] Done.")
        if "matching_count" not in user_cols:
            print("[MIGRATE] Adding matching_count column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN matching_count INTEGER NOT NULL DEFAULT 0"
                ))
            print("[MIGRATE] Done.")

        if "failed_security_attempts" not in user_cols:
            print("[MIGRATE] Adding failed_security_attempts column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN failed_security_attempts INTEGER NOT NULL DEFAULT 0"
                ))
            print("[MIGRATE] Done.")
        if "security_lockout_until" not in user_cols:
            print("[MIGRATE] Adding security_lockout_until column to users table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN security_lockout_until DATETIME"
                ))
            print("[MIGRATE] Done.")

        # Encrypt existing plaintext TOTP secrets if TOTP_ENCRYPTION_KEY is set
        _migrate_totp_secrets()

    # Migrate user_offers table
    if "user_offers" in insp.get_table_names():
        uo_cols = [c["name"] for c in insp.get_columns("user_offers")]
        if "cv_match_score" not in uo_cols:
            print("[MIGRATE] Adding cv_match_score column to user_offers table...")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE user_offers ADD COLUMN cv_match_score FLOAT"
                ))
            print("[MIGRATE] Done.")

    # Fix company names that are actually descriptions (> 50 chars of prose)
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE offers SET company = 'Non renseigné' "
            "WHERE length(company) > 50"
        ))
        if result.rowcount > 0:
            print(f"[MIGRATE] Fixed {result.rowcount} offers with description as company name.")


def _migrate_totp_secrets():
    """Encrypt any plaintext TOTP secrets in the DB using Fernet if key is available."""
    from config import Config
    key = Config.TOTP_ENCRYPTION_KEY
    if not key:
        return
    try:
        from cryptography.fernet import Fernet, InvalidToken
        f = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        print(f"[MIGRATE] TOTP encryption: invalid TOTP_ENCRYPTION_KEY — {exc}")
        return

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL AND totp_secret != ''"
        )).fetchall()

    migrated = 0
    for row in rows:
        user_id, secret = row[0], row[1]
        # Try to decrypt — if it succeeds it's already encrypted
        try:
            f.decrypt(secret.encode())
            continue  # Already encrypted
        except (InvalidToken, Exception):
            pass  # Plaintext — encrypt it
        encrypted = f.encrypt(secret.encode()).decode()
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE users SET totp_secret = :s WHERE id = :id"
            ), {"s": encrypted, "id": user_id})
        migrated += 1

    if migrated > 0:
        print(f"[MIGRATE] Encrypted {migrated} plaintext TOTP secret(s).")


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

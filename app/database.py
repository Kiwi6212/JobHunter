"""
Database connection and session management for JobHunter.
Handles SQLite database initialization and provides session factory.
"""

import os
from pathlib import Path
from sqlalchemy import create_engine
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
    echo=Config.DEBUG,  # Log SQL queries in debug mode
    connect_args={"check_same_thread": False}  # Allow SQLite to work with multiple threads
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

    print("✓ Database initialized successfully!")
    print(f"✓ Tables created: {', '.join(Base.metadata.tables.keys())}")


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
    ⚠️ WARNING: This will delete all data! Use only for development/testing.
    """
    print("⚠️  Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("✓ All tables dropped")


def reset_db():
    """
    Reset the database by dropping and recreating all tables.
    ⚠️ WARNING: This will delete all data! Use only for development/testing.
    """
    print("⚠️  Resetting database...")
    drop_all_tables()
    init_db()
    print("✓ Database reset complete")

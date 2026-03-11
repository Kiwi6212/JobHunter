"""
Database models for JobHunter application.
Defines the structure for offers and tracking tables.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Offer(Base):
    """Job offer model - stores scraped job listings."""

    __tablename__ = "offers"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Job details
    title = Column(String(255), nullable=False)
    company = Column(String(255), nullable=False)
    location = Column(String(255), nullable=True)
    contract_type = Column(String(50), nullable=True)  # alternance, CDI, etc.
    description = Column(Text, nullable=True)
    url = Column(String(512), nullable=False, unique=True)

    # Source tracking
    source = Column(String(50), nullable=False)  # france_travail, wttj, indeed, etc.
    external_id = Column(String(255), nullable=True)  # ID from source for deduplication
    offer_type = Column(String(20), nullable=False, default="job")  # job or recruiter

    # Dates
    posted_date = Column(DateTime, nullable=True)  # When posted by company
    found_date = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))  # When scraped

    # Scoring
    relevance_score = Column(Float, nullable=True, default=0.0)
    cv_match_score = Column(Float, nullable=True, default=None)  # TF-IDF cosine sim × 100

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=lambda: datetime.now(timezone.utc))

    # Active flag (False = dead link / expired)
    is_active = Column(Boolean, nullable=False, default=True)

    # Domain (for multi-user filtering)
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True, index=True)
    domain = relationship("Domain", back_populates="offers")

    # Relationships
    tracking = relationship("Tracking", back_populates="offer", uselist=False, cascade="all, delete-orphan")
    user_offers = relationship("UserOffer", back_populates="offer", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Offer(id={self.id}, title='{self.title}', company='{self.company}')>"


class Tracking(Base):
    """Application tracking model - tracks user's application progress per offer."""

    __tablename__ = "tracking"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key
    offer_id = Column(Integer, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Status workflow
    status = Column(
        String(50),
        nullable=False,
        default="New"
    )  # New, Applied, Followed up, Interview, Accepted, Rejected, No response

    # Checkboxes
    cv_sent = Column(Boolean, nullable=False, default=False)
    follow_up_done = Column(Boolean, nullable=False, default=False)

    # Date fields
    date_sent = Column(DateTime, nullable=True)  # When CV was sent
    follow_up_date = Column(DateTime, nullable=True)  # When follow-up was done

    # Notes
    notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=lambda: datetime.now(timezone.utc))

    # Relationship
    offer = relationship("Offer", back_populates="tracking")

    def __repr__(self):
        return f"<Tracking(id={self.id}, offer_id={self.offer_id}, status='{self.status}')>"


class Domain(Base):
    """Job search domain / specialty (e.g. Sysadmin, Développement)."""

    __tablename__ = "domains"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(String(255), nullable=True)

    users = relationship("User", back_populates="domain")
    offers = relationship("Offer", back_populates="domain")

    def __repr__(self):
        return f"<Domain(id={self.id}, name='{self.name}')>"


class User(Base):
    """Application user with DB-backed credentials and optional domain scope."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="user")  # admin, user, viewer
    domain_id = Column(Integer, ForeignKey("domains.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    email_confirmed = Column(Boolean, nullable=False, default=True)

    # Two-factor authentication (TOTP / Google Authenticator)
    totp_secret = Column(String(64), nullable=True, default=None)
    totp_enabled = Column(Boolean, nullable=False, default=False)

    # Contact
    email = Column(String(255), nullable=True, default=None)

    # Account recovery via security question
    security_question = Column(String(255), nullable=True, default=None)
    security_answer_hash = Column(String(255), nullable=True, default=None)

    # Activity tracking
    last_login = Column(DateTime, nullable=True, default=None)
    claude_tokens_used = Column(Integer, nullable=False, default=0)
    matching_count = Column(Integer, nullable=False, default=0)

    # Weekly quotas (role=user only; admin has no limit)
    weekly_matches_used = Column(Integer, nullable=False, default=0)
    weekly_letters_used = Column(Integer, nullable=False, default=0)
    quota_reset_at = Column(DateTime, nullable=True, default=None)

    # Security question brute-force protection
    failed_security_attempts = Column(Integer, nullable=False, default=0)
    security_lockout_until = Column(DateTime, nullable=True, default=None)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=lambda: datetime.now(timezone.utc))

    domain = relationship("Domain", back_populates="users")
    user_offers = relationship("UserOffer", back_populates="user", cascade="all, delete-orphan")
    password_resets = relationship("PasswordReset", back_populates="user", cascade="all, delete-orphan")
    email_confirmations = relationship("EmailConfirmation", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"


class UserOffer(Base):
    """Per-user tracking of a job offer (replaces Tracking for DB users)."""

    __tablename__ = "user_offers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    offer_id = Column(Integer, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)

    # Same tracking fields as Tracking
    status = Column(String(50), nullable=False, default="New")
    cv_sent = Column(Boolean, nullable=False, default=False)
    follow_up_done = Column(Boolean, nullable=False, default=False)
    date_sent = Column(DateTime, nullable=True)
    follow_up_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # Per-user CV match score (replaces Offer.cv_match_score for DB users)
    cv_match_score = Column(Float, nullable=True, default=None)

    # Favorites
    is_favorite = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="user_offers")
    offer = relationship("Offer", back_populates="user_offers")

    __table_args__ = (UniqueConstraint("user_id", "offer_id"),)

    def __repr__(self):
        return f"<UserOffer(user_id={self.user_id}, offer_id={self.offer_id}, status='{self.status}')>"


class PasswordReset(Base):
    """Single-use, time-limited password reset tokens."""

    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    used = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="password_resets")

    def __repr__(self):
        return f"<PasswordReset(user_id={self.user_id}, used={self.used})>"


class EmailConfirmation(Base):
    """Single-use, time-limited email confirmation tokens for registration."""

    __tablename__ = "email_confirmations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    used = Column(Boolean, nullable=False, default=False)

    user = relationship("User", back_populates="email_confirmations")

    def __repr__(self):
        return f"<EmailConfirmation(user_id={self.user_id}, used={self.used})>"

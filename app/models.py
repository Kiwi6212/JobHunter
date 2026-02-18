"""
Database models for JobHunter application.
Defines the structure for offers and tracking tables.
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey
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
    found_date = Column(DateTime, nullable=False, default=datetime.utcnow)  # When scraped

    # Scoring
    relevance_score = Column(Float, nullable=True, default=0.0)
    cv_match_score = Column(Float, nullable=True, default=None)  # TF-IDF cosine sim × 100

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    tracking = relationship("Tracking", back_populates="offer", uselist=False, cascade="all, delete-orphan")

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    offer = relationship("Offer", back_populates="tracking")

    def __repr__(self):
        return f"<Tracking(id={self.id}, offer_id={self.offer_id}, status='{self.status}')>"

"""
Database models for the Voice-to-CRM pipeline.

Tables:
- meetings: Calendar events that have been detected and may need voice notes
- voice_notes: Audio recordings and their transcriptions
- processed_results: AI-extracted outputs from voice notes
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

import enum


class MeetingStatus(str, enum.Enum):
    """Lifecycle of a detected calendar meeting."""

    DETECTED = "detected"  # Meeting found in calendar, not yet ended
    PROMPT_SENT = "prompt_sent"  # Slack prompt sent to user
    NOTE_RECEIVED = "note_received"  # Voice note uploaded
    PROCESSED = "processed"  # AI processing complete, outputs distributed
    SKIPPED = "skipped"  # User dismissed or meeting was filtered out
    BATCH_REMINDED = "batch_reminded"  # Included in end-of-day batch reminder


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    """A calendar event detected by the polling service."""

    __tablename__ = "meetings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    calendar_event_id = Column(
        String(512), unique=True, nullable=False, index=True
    )  # Google Calendar event ID
    title = Column(String(500), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)

    # Attendee info stored as comma-separated for simplicity in v1.
    # Format: "Name <email>, Name <email>"
    attendee_names = Column(Text, default="")
    attendee_emails = Column(Text, default="")

    # Event metadata
    description = Column(Text, default="")
    organizer_email = Column(String(320), default="")

    # State tracking
    status = Column(
        String(50), default=MeetingStatus.DETECTED, nullable=False, index=True
    )
    prompt_sent_at = Column(DateTime(timezone=True), nullable=True)
    batch_reminded_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    voice_note = relationship(
        "VoiceNote", back_populates="meeting", uselist=False, cascade="all, delete-orphan"
    )

    def external_attendee_list(self, internal_domain: str) -> list[dict]:
        """Parse attendee fields and return only external attendees."""
        names = [n.strip() for n in self.attendee_names.split(",") if n.strip()]
        emails = [e.strip() for e in self.attendee_emails.split(",") if e.strip()]
        result = []
        for i, email in enumerate(emails):
            if not email.endswith(f"@{internal_domain}"):
                name = names[i] if i < len(names) else email.split("@")[0]
                result.append({"name": name, "email": email})
        return result

    def primary_external_attendee(self, internal_domain: str) -> Optional[dict]:
        """Get the first external attendee (most likely the key contact)."""
        externals = self.external_attendee_list(internal_domain)
        return externals[0] if externals else None


class VoiceNote(Base):
    """An audio recording uploaded by the user after a meeting."""

    __tablename__ = "voice_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(
        Integer, ForeignKey("meetings.id"), nullable=False, unique=True, index=True
    )

    # Audio file info
    audio_file_path = Column(String(1000), nullable=False)
    audio_duration_seconds = Column(Integer, nullable=True)

    # Transcription
    transcript = Column(Text, default="")
    transcription_completed_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    meeting = relationship("Meeting", back_populates="voice_note")
    processed_result = relationship(
        "ProcessedResult",
        back_populates="voice_note",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ProcessedResult(Base):
    """Structured output from Claude's analysis of a voice note."""

    __tablename__ = "processed_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    voice_note_id = Column(
        Integer, ForeignKey("voice_notes.id"), nullable=False, unique=True, index=True
    )

    # AI outputs stored as JSON strings for flexibility in v1
    summary = Column(Text, default="")
    action_items_json = Column(Text, default="[]")  # JSON array
    follow_ups_json = Column(Text, default="[]")  # JSON array
    proposed_tags_json = Column(Text, default="[]")  # JSON array
    keywords_json = Column(Text, default="[]")  # JSON array of keyword strings
    relationship_signals_json = Column(Text, default="[]")  # JSON array
    contact_note = Column(Text, default="")  # Cleaned note for CRM

    # Distribution tracking
    slack_daniel_sent_at = Column(DateTime(timezone=True), nullable=True)
    slack_justine_sent_at = Column(DateTime(timezone=True), nullable=True)
    sheets_logged_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    voice_note = relationship("VoiceNote", back_populates="processed_result")


# --- Database initialization ---


def create_db_engine(database_url: str):
    """Create SQLAlchemy engine with connection pooling."""
    return create_engine(
        database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before using them
        echo=False,
    )


def create_session_factory(engine) -> sessionmaker:
    """Create a session factory bound to the engine."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine):
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)

import uuid
import json
from datetime import datetime
from typing import Optional, List

from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from pydantic import BaseModel

from database import Base


# ══════════════════════════════════════════════════════════════════════════════
# SQLAlchemy ORM Models (database tables)
# ══════════════════════════════════════════════════════════════════════════════

class User(Base):
    """Stores authenticated Google users and their OAuth tokens."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    picture = Column(String, nullable=True)          # Google profile picture URL
    google_access_token = Column(String, nullable=True)
    google_refresh_token = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    emails = relationship("Email", back_populates="owner", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="owner", cascade="all, delete-orphan")


class Email(Base):
    """Cached Gmail messages enriched with Gemini AI analysis."""
    __tablename__ = "emails"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Gmail-sourced fields
    message_id = Column(String, unique=True, index=True, nullable=False)  # Gmail message ID
    sender_name = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    body = Column(Text, nullable=True)
    snippet = Column(String, nullable=True)
    date_str = Column(String, nullable=True)          # raw date string from Gmail
    is_read = Column(Boolean, default=False)

    # Gemini AI analysis fields
    category = Column(String, nullable=True)          # urgent | meeting | action | newsletter | fyi
    summary = Column(Text, nullable=True)
    action_items = Column(Text, nullable=True)        # JSON-encoded list
    meeting_detected = Column(Boolean, default=False)
    meeting_title = Column(String, nullable=True)
    meeting_date = Column(String, nullable=True)
    meeting_time = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="emails")

    # Helper to get/set action_items as a Python list
    def get_action_items(self) -> list:
        if self.action_items:
            try:
                return json.loads(self.action_items)
            except Exception:
                return []
        return []

    def set_action_items(self, items: list):
        self.action_items = json.dumps(items)


class Meeting(Base):
    """Meetings extracted from Gmail emails by Gemini AI."""
    __tablename__ = "meetings"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    email_id = Column(String, ForeignKey("emails.id"), nullable=True)

    title = Column(String, nullable=False)
    date = Column(String, nullable=True)              # e.g. "2024-09-15"
    time = Column(String, nullable=True)              # e.g. "14:00"
    source_email_subject = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="meetings")


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic Schemas (API request/response shapes)
# ══════════════════════════════════════════════════════════════════════════════

class MeetingInfo(BaseModel):
    detected: bool = False
    title: str = ""
    date: str = ""
    time: str = ""


class EmailMessage(BaseModel):
    """Full email detail as returned by API."""
    id: str
    message_id: str
    sender_name: Optional[str]
    sender_email: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    snippet: Optional[str]
    date_str: Optional[str]
    is_read: bool
    category: Optional[str]
    summary: Optional[str]
    action_items: List[str] = []
    meeting_detected: bool = False
    meeting_title: Optional[str]
    meeting_date: Optional[str]
    meeting_time: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_items(cls, email: Email) -> "EmailMessage":
        data = {
            "id": email.id,
            "message_id": email.message_id,
            "sender_name": email.sender_name,
            "sender_email": email.sender_email,
            "subject": email.subject,
            "body": email.body,
            "snippet": email.snippet,
            "date_str": email.date_str,
            "is_read": email.is_read,
            "category": email.category,
            "summary": email.summary,
            "action_items": email.get_action_items(),
            "meeting_detected": email.meeting_detected or False,
            "meeting_title": email.meeting_title,
            "meeting_date": email.meeting_date,
            "meeting_time": email.meeting_time,
            "created_at": email.created_at,
        }
        return cls(**data)


class UserSession(BaseModel):
    """User info embedded in session / returned to frontend."""
    user_id: str
    email: str
    name: Optional[str]
    picture: Optional[str]


class MeetingEvent(BaseModel):
    """Meeting event as returned from /api/meetings."""
    id: str
    email_id: Optional[str]
    title: str
    date: Optional[str]
    time: Optional[str]
    source_email_subject: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class EmailStats(BaseModel):
    """Counts per category for the sidebar badges."""
    total: int = 0
    urgent: int = 0
    meeting: int = 0
    action: int = 0
    newsletter: int = 0
    fyi: int = 0
    unread: int = 0


# ── Legacy aliases kept for backward compatibility ─────────────────────────────
class EmailItem(Email):
    """Alias — use Email instead."""
    __abstract__ = True


class EmailItemRead(EmailMessage):
    """Alias — use EmailMessage instead."""
    pass


class ChatRequest(BaseModel):
    prompt: str
    context: str


class ChatResponse(BaseModel):
    response: str

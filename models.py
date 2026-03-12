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

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    picture = Column(String(1024), nullable=True)          # Google profile picture URL
    google_access_token = Column(String(2048), nullable=True)
    google_refresh_token = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    emails = relationship("Email", back_populates="owner", cascade="all, delete-orphan")
    meetings = relationship("Meeting", back_populates="owner", cascade="all, delete-orphan")


class Email(Base):
    """Cached Gmail messages enriched with Gemini AI analysis."""
    __tablename__ = "emails"

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    # Gmail-sourced fields
    message_id = Column(String(255), unique=True, index=True, nullable=False)  # Gmail message ID
    sender_name = Column(String(255), nullable=True)
    sender_email = Column(String(255), nullable=True)
    subject = Column(String(512), nullable=True)
    body = Column(Text, nullable=True)
    snippet = Column(String(1024), nullable=True)
    date_str = Column(String(100), nullable=True)          # raw date string from Gmail
    is_read = Column(Boolean, default=False)

    # Gemini AI analysis fields
    category = Column(String(50), nullable=True)          # urgent | meeting | action | form | newsletter | fyi
    priority = Column(String(20), nullable=True, default="low")   # high | medium | low
    needs_attention_now = Column(Boolean, default=False)
    waiting = Column(Boolean, default=False)
    summary = Column(Text, nullable=True)
    action_items = Column(Text, nullable=True)        # JSON-encoded list
    form_detected = Column(Boolean, default=False)
    form_description = Column(String(1024), nullable=True)
    meeting_detected = Column(Boolean, default=False)
    meeting_title = Column(String(255), nullable=True)
    meeting_date = Column(String(50), nullable=True)
    meeting_time = Column(String(50), nullable=True)
    meeting_duration = Column(String(10), nullable=True)  # duration_minutes as string
    body_html = Column(Text, nullable=True)               # raw HTML for iframe display

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

    id = Column(String(36), primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    email_id = Column(String(36), ForeignKey("emails.id"), nullable=True)

    title = Column(String(255), nullable=False)
    date = Column(String(50), nullable=True)              # e.g. "2024-09-15"
    time = Column(String(50), nullable=True)              # e.g. "14:00"
    source_email_subject = Column(String(512), nullable=True)

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
    body_html: Optional[str] = None
    snippet: Optional[str]
    date_str: Optional[str]
    is_read: bool
    category: Optional[str]
    priority: Optional[str] = "low"
    needs_attention_now: bool = False
    waiting: bool = False
    summary: Optional[str]
    action_items: List[str] = []
    form_detected: bool = False
    form_description: Optional[str] = None
    meeting_detected: bool = False
    meeting_title: Optional[str]
    meeting_date: Optional[str]
    meeting_time: Optional[str]
    meeting_duration: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_items(cls, email) -> "EmailMessage":
        data = {
            "id": email.id,
            "message_id": email.message_id,
            "sender_name": email.sender_name,
            "sender_email": email.sender_email,
            "subject": email.subject,
            "body": email.body,
            "body_html": email.body_html,
            "snippet": email.snippet,
            "date_str": email.date_str,
            "is_read": email.is_read,
            "category": email.category,
            "priority": email.priority or "low",
            "needs_attention_now": email.needs_attention_now or False,
            "waiting": email.waiting or False,
            "summary": email.summary,
            "action_items": email.get_action_items(),
            "form_detected": email.form_detected or False,
            "form_description": email.form_description,
            "meeting_detected": email.meeting_detected or False,
            "meeting_title": email.meeting_title,
            "meeting_date": email.meeting_date,
            "meeting_time": email.meeting_time,
            "meeting_duration": email.meeting_duration,
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

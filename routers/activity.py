from datetime import datetime, date, timedelta
from typing import List, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Email, Meeting
from auth import get_current_user

router = APIRouter(prefix="/api/activity", tags=["activity"])


class ActivityItem(BaseModel):
    """A single item in the activity timeline feed."""
    id: str
    type: str        # "email_urgent" | "email_action" | "meeting" | "email_new"
    title: str
    description: str
    time: str        # ISO 8601 string
    badge: str       # label shown on the badge chip
    icon: str        # icon name for the frontend to render


@router.get("", response_model=List[ActivityItem])
async def get_activity(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """
    Return a unified activity timeline combining:
    - Recent urgent emails (last 24 h)
    - Emails with action items (last 24 h)
    - All upcoming / recent meetings
    - Other recent emails (last 6 h)

    The list is sorted newest first, capped at 30 items.
    """
    try:
        now = datetime.utcnow()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_6h = now - timedelta(hours=6)

        items: List[ActivityItem] = []

        # ── Meetings ──────────────────────────────────────────────────────────
        meetings = (
            db.query(Meeting)
            .filter(Meeting.user_id == user_id)
            .order_by(Meeting.created_at.desc())
            .limit(10)
            .all()
        )
        for m in meetings:
            date_label = f"{m.date} {m.time}".strip() if (m.date or m.time) else "Time TBD"
            items.append(ActivityItem(
                id=f"meeting-{m.id}",
                type="meeting",
                title=m.title or "Meeting Detected",
                description=f"From: {m.source_email_subject or 'email'} • {date_label}",
                time=m.created_at.isoformat(),
                badge="Meeting",
                icon="calendar",
            ))

        # ── Urgent emails (last 24h) ──────────────────────────────────────────
        urgent_emails = (
            db.query(Email)
            .filter(
                Email.user_id == user_id,
                Email.category == "urgent",
                Email.created_at >= cutoff_24h,
            )
            .order_by(Email.created_at.desc())
            .limit(10)
            .all()
        )
        already_added_email_ids = set()
        for e in urgent_emails:
            already_added_email_ids.add(e.id)
            items.append(ActivityItem(
                id=f"email-urgent-{e.id}",
                type="email_urgent",
                title=e.subject or "(No Subject)",
                description=e.summary or e.snippet or "Urgent email requiring attention.",
                time=e.created_at.isoformat(),
                badge="Urgent",
                icon="alert",
            ))

        # ── Action emails (last 24h) ──────────────────────────────────────────
        action_emails = (
            db.query(Email)
            .filter(
                Email.user_id == user_id,
                Email.category == "action",
                Email.created_at >= cutoff_24h,
            )
            .order_by(Email.created_at.desc())
            .limit(10)
            .all()
        )
        for e in action_emails:
            already_added_email_ids.add(e.id)
            action_items = e.get_action_items()
            desc = action_items[0] if action_items else (e.summary or "Pending action item.")
            items.append(ActivityItem(
                id=f"email-action-{e.id}",
                type="email_action",
                title=e.subject or "(No Subject)",
                description=desc,
                time=e.created_at.isoformat(),
                badge="Action",
                icon="check-circle",
            ))

        # ── Recent new emails (last 6h, not already covered) ──────────────────
        recent_emails = (
            db.query(Email)
            .filter(
                Email.user_id == user_id,
                Email.created_at >= cutoff_6h,
                Email.category.notin_(["urgent", "action"]),
            )
            .order_by(Email.created_at.desc())
            .limit(5)
            .all()
        )
        for e in recent_emails:
            if e.id not in already_added_email_ids:
                items.append(ActivityItem(
                    id=f"email-new-{e.id}",
                    type="email_new",
                    title=e.subject or "(No Subject)",
                    description=e.summary or e.snippet or "New email received.",
                    time=e.created_at.isoformat(),
                    badge=e.category.capitalize() if e.category else "FYI",
                    icon="mail",
                ))

        # Sort by time descending and cap at 30
        items.sort(key=lambda x: x.time, reverse=True)
        return items[:30]

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch activity: {e}")

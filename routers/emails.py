import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import Email, Meeting, EmailMessage, EmailStats
from auth import get_current_user
from gmail_service import GmailService
from gemini_service import analyze_emails_batch
from calendar_service import check_calendar_conflicts, add_calendar_event, get_todays_events

router = APIRouter(prefix="/api/emails", tags=["emails"])


# ── Pydantic models for new endpoints ─────────────────────────────────────────

class CalendarAddRequest(BaseModel):
    """Request body for adding a meeting to Google Calendar."""
    title: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    duration_minutes: Optional[int] = 30
    description: Optional[str] = ""
    override_conflict: Optional[bool] = False


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_email_response(email: Email) -> dict:
    """Convert an ORM Email row to a JSON-serialisable dict."""
    return EmailMessage.from_orm_with_items(email).model_dump()


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[EmailMessage])
async def get_emails(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        from models import User
        emails = (
            db.query(Email)
            .filter(Email.user_id == user_id)
            .order_by(Email.created_at.desc())
            .all()
        )

        if not emails:
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.google_access_token:
                await _sync_emails(user, db)
                emails = (
                    db.query(Email)
                    .filter(Email.user_id == user_id)
                    .order_by(Email.created_at.desc())
                    .all()
                )

        return [EmailMessage.from_orm_with_items(e) for e in emails]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {e}")


@router.get("/stats", response_model=EmailStats)
async def get_email_stats(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        emails = db.query(Email).filter(Email.user_id == user_id).all()
        stats = EmailStats(total=len(emails), unread=sum(1 for e in emails if not e.is_read))
        for e in emails:
            cat = (e.category or "fyi").lower()
            if cat == "urgent":
                stats.urgent += 1
            elif cat == "meeting":
                stats.meeting += 1
            elif cat == "action":
                stats.action += 1
            elif cat == "newsletter":
                stats.newsletter += 1
            else:
                stats.fyi += 1
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {e}")


@router.get("/calendar/today")
async def get_today_calendar(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        from models import User
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.google_access_token:
            return []
        events = await asyncio.to_thread(
            get_todays_events,
            user.google_access_token,
            user.google_refresh_token,
        )
        return events
    except Exception as e:
        print(f"[/calendar/today] Error: {e}")
        return []


@router.post("/sync")
async def sync_emails(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        from models import User
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.google_access_token:
            raise HTTPException(status_code=400, detail="No Gmail token available — please re-authenticate.")

        new_count = await _sync_emails(user, db)
        return {"status": "ok", "new_emails": new_count, "message": f"Synced {new_count} new email(s)."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")


@router.get("/{email_id}", response_model=EmailMessage)
async def get_email(
    email_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        email = (
            db.query(Email)
            .filter(Email.id == email_id, Email.user_id == user_id)
            .first()
        )
        if not email:
            raise HTTPException(status_code=404, detail="Email not found.")

        if not email.is_read:
            email.is_read = True
            db.commit()
            db.refresh(email)

        return EmailMessage.from_orm_with_items(email)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch email: {e}")


@router.post("/{email_id}/add-to-calendar")
async def add_email_to_calendar(
    email_id: str,
    request: CalendarAddRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    try:
        from models import User
        email = (
            db.query(Email)
            .filter(Email.id == email_id, Email.user_id == user_id)
            .first()
        )
        if not email:
            raise HTTPException(status_code=404, detail="Email not found.")

        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.google_access_token:
            raise HTTPException(status_code=400, detail="No Google token — please re-authenticate.")

        title = request.title or email.meeting_title or email.subject or "Meeting"
        date = request.date or email.meeting_date or ""
        time = request.time or email.meeting_time or ""
        duration = request.duration_minutes or int(email.meeting_duration or 30)
        description = request.description or f"Added from email: {email.subject}"

        if not date:
            raise HTTPException(status_code=400, detail="No meeting date available. Please provide a date.")

        if not request.override_conflict:
            conflicts = await asyncio.to_thread(
                check_calendar_conflicts,
                user.google_access_token,
                user.google_refresh_token,
                date,
                time,
                duration,
            )
            if conflicts:
                return {
                    "status": "conflict",
                    "message": f"You have {len(conflicts)} conflicting event(s) during this time.",
                    "conflicts": conflicts,
                }

        event_link = await asyncio.to_thread(
            add_calendar_event,
            user.google_access_token,
            user.google_refresh_token,
            title,
            date,
            time,
            duration,
            description,
        )

        if event_link:
            return {
                "status": "created",
                "message": f"Event '{title}' added to your calendar.",
                "event_url": event_link,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create calendar event.")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calendar error: {e}")


# ── Internal Sync Logic ────────────────────────────────────────────────────────

async def _sync_emails(user, db: Session) -> int:
    """
    Fetch emails from Gmail, run Gemini analysis, persist to DB.
    Returns the number of newly stored emails.
    """
    from models import Meeting

    gmail = GmailService(user.google_access_token, user.google_refresh_token)

    # Gmail client is sync — run in thread
    raw_emails = await asyncio.to_thread(gmail.fetch_emails, 20)
    if not raw_emails:
        return 0

    # analyze_emails_batch is now async — await it directly
    analyses = await analyze_emails_batch(raw_emails)

    new_count = 0
    for raw, analysis in zip(raw_emails, analyses):
        existing = db.query(Email).filter(Email.message_id == raw["message_id"]).first()
        if existing:
            continue

        meeting_info = analysis.get("meeting", {})
        duration_val = meeting_info.get("duration_minutes", 30)

        email_row = Email(
            user_id=user.id,
            message_id=raw["message_id"],
            sender_name=raw.get("sender_name"),
            sender_email=raw.get("sender_email"),
            subject=raw.get("subject"),
            body=raw.get("body"),
            body_html=raw.get("body_html"),
            snippet=raw.get("snippet"),
            date_str=raw.get("date_str"),
            is_read=raw.get("is_read", False),
            category=analysis.get("category", "fyi"),
            priority=analysis.get("priority", "low"),
            needs_attention_now=analysis.get("needs_attention_now", False),
            waiting=analysis.get("waiting", False),
            summary=analysis.get("summary"),
            form_detected=analysis.get("form_detected", False),
            form_description=analysis.get("form_description", ""),
            meeting_detected=meeting_info.get("detected", False),
            meeting_title=meeting_info.get("title"),
            meeting_date=meeting_info.get("date"),
            meeting_time=meeting_info.get("time"),
            meeting_duration=str(duration_val) if duration_val else "30",
        )
        email_row.set_action_items(analysis.get("action_items", []))
        db.add(email_row)
        db.flush()

        if email_row.meeting_detected and meeting_info.get("title"):
            meeting = Meeting(
                user_id=user.id,
                email_id=email_row.id,
                title=meeting_info["title"],
                date=meeting_info.get("date"),
                time=meeting_info.get("time"),
                source_email_subject=raw.get("subject"),
            )
            db.add(meeting)

        new_count += 1

    db.commit()

    # Persist refreshed token if it changed
    user.google_access_token = gmail.access_token
    db.commit()

    return new_count
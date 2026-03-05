import asyncio
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Email, Meeting, EmailMessage, EmailStats
from auth import get_current_user
from gmail_service import GmailService
from gemini_service import analyze_emails_batch

router = APIRouter(prefix="/api/emails", tags=["emails"])


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
    """
    Return all cached emails for the authenticated user, newest first.
    If the cache is empty, trigger a first-time sync automatically.
    """
    try:
        from models import User
        emails = (
            db.query(Email)
            .filter(Email.user_id == user_id)
            .order_by(Email.created_at.desc())
            .all()
        )

        # Auto-sync on first visit
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
    """Return per-category email counts for the sidebar badges."""
    try:
        emails = db.query(Email).filter(Email.user_id == user_id).all()
        stats = EmailStats(
            total=len(emails),
            unread=sum(1 for e in emails if not e.is_read),
        )
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


@router.get("/{email_id}", response_model=EmailMessage)
async def get_email(
    email_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Return a single email by its internal DB id. Marks it as read."""
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


@router.post("/sync")
async def sync_emails(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """
    Force re-fetch the latest 20 emails from Gmail, run Gemini analysis,
    and store/update them in the database.  Returns a summary of what changed.
    """
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


# ── Internal Sync Logic ────────────────────────────────────────────────────────

async def _sync_emails(user, db: Session) -> int:
    """
    Fetch emails from Gmail, run Gemini analysis, persist to DB.
    Also creates Meeting records for any meetings detected.
    Returns the number of newly stored emails.
    """
    from models import Meeting

    gmail = GmailService(user.google_access_token, user.google_refresh_token)

    # Fetch in a thread since the Google client is synchronous
    raw_emails = await asyncio.to_thread(gmail.fetch_emails, 20)
    if not raw_emails:
        return 0

    # Run Gemini analysis in a thread
    analyses = await asyncio.to_thread(analyze_emails_batch, raw_emails)

    new_count = 0
    for raw, analysis in zip(raw_emails, analyses):
        # Skip if already in DB
        existing = db.query(Email).filter(Email.message_id == raw["message_id"]).first()
        if existing:
            continue

        email_row = Email(
            user_id=user.id,
            message_id=raw["message_id"],
            sender_name=raw.get("sender_name"),
            sender_email=raw.get("sender_email"),
            subject=raw.get("subject"),
            body=raw.get("body"),
            snippet=raw.get("snippet"),
            date_str=raw.get("date_str"),
            is_read=raw.get("is_read", False),
            category=analysis.get("category", "fyi"),
            summary=analysis.get("summary"),
            meeting_detected=analysis.get("meeting", {}).get("detected", False),
            meeting_title=analysis.get("meeting", {}).get("title"),
            meeting_date=analysis.get("meeting", {}).get("date"),
            meeting_time=analysis.get("meeting", {}).get("time"),
        )
        email_row.set_action_items(analysis.get("action_items", []))
        db.add(email_row)
        db.flush()  # get email_row.id assigned

        # Create Meeting record if a meeting was detected
        if email_row.meeting_detected and analysis.get("meeting", {}).get("title"):
            meeting = Meeting(
                user_id=user.id,
                email_id=email_row.id,
                title=analysis["meeting"]["title"],
                date=analysis["meeting"].get("date"),
                time=analysis["meeting"].get("time"),
                source_email_subject=raw.get("subject"),
            )
            db.add(meeting)

        new_count += 1

    db.commit()

    # Update user's access token in case it was refreshed
    user.google_access_token = gmail.access_token
    db.commit()

    return new_count

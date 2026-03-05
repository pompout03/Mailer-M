from datetime import datetime, date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Email, Meeting, MeetingEvent
from auth import get_current_user

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _row_to_event(m: Meeting) -> MeetingEvent:
    return MeetingEvent(
        id=m.id,
        email_id=m.email_id,
        title=m.title,
        date=m.date,
        time=m.time,
        source_email_subject=m.source_email_subject,
        created_at=m.created_at,
    )


@router.get("", response_model=List[MeetingEvent])
async def get_all_meetings(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Return all meetings detected from emails for the authenticated user."""
    try:
        meetings = (
            db.query(Meeting)
            .filter(Meeting.user_id == user_id)
            .order_by(Meeting.created_at.desc())
            .all()
        )
        return [_row_to_event(m) for m in meetings]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch meetings: {e}")


@router.get("/today", response_model=List[MeetingEvent])
async def get_todays_meetings(
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user),
):
    """Return meetings whose date matches today's date (YYYY-MM-DD format)."""
    try:
        today_str = date.today().isoformat()  # e.g. "2024-09-15"
        meetings = (
            db.query(Meeting)
            .filter(Meeting.user_id == user_id, Meeting.date == today_str)
            .order_by(Meeting.time)
            .all()
        )
        return [_row_to_event(m) for m in meetings]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch today's meetings: {e}")

"""
calendar_service.py
────────────────────
Google Calendar integration for MailMind AI Chief of Staff.
Handles authentication, token refresh, and event management.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

class CalendarService:
    """
    Service class for interacting with the Google Calendar API.
    Handles token refresh and persists the new token in self.access_token.
    """
    
    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/calendar.events",
    ]

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._service = None

    def _get_credentials(self) -> Credentials:
        """Build Google credentials, refreshing the token if needed."""
        creds = Credentials(
            token=self.access_token,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=self.SCOPES,
        )
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
                self.access_token = creds.token
            except Exception as e:
                print(f"[CalendarService] Token refresh failed: {e}")
        return creds

    def _get_service(self):
        """Lazy-initialize the Calendar API client."""
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def _parse_datetime(self, date_str: str, time_str: str) -> Optional[datetime]:
        """Parse a YYYY-MM-DD date and HH:MM time into a UTC-aware datetime."""
        if not date_str:
            return None
        try:
            if time_str:
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            else:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                dt = dt.replace(hour=9, minute=0)  # default to 9 AM
            
            # For simplicity in this MVP, we treat parsed times as UTC.
            # In a full app, you'd want to use the user's preferred timezone.
            return dt.replace(tzinfo=timezone.utc)
        except ValueError as e:
            print(f"[CalendarService] Date parse error: {e}")
            return None

    # -- Public Methods ---------------------------------------------------------

    def check_conflicts(self, date: str, time: str, duration_minutes: int = 30) -> List[dict]:
        """Check for Google Calendar conflicts for the given time slot."""
        try:
            service = self._get_service()
            start_dt = self._parse_datetime(date, time)
            if not start_dt:
                return []

            end_dt = start_dt + timedelta(minutes=duration_minutes)

            # Use freebusy query
            body = {
                "timeMin": start_dt.isoformat(),
                "timeMax": end_dt.isoformat(),
                "items": [{"id": "primary"}],
            }
            freebusy = service.freebusy().query(body=body).execute()
            busy_slots = freebusy.get("calendars", {}).get("primary", {}).get("busy", [])

            if not busy_slots:
                return []

            # Fetch actual event details
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_dt.isoformat(),
                    timeMax=end_dt.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])
            conflicts = []
            for ev in events:
                conflicts.append({
                    "title": ev.get("summary", "Untitled Event"),
                    "start": ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")),
                    "end": ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", "")),
                    "link": ev.get("htmlLink", ""),
                })
            return conflicts

        except Exception as e:
            print(f"[CalendarService] check_conflicts error: {e}")
            return []

    def add_event(self, title: str, date: str, time: str, duration_minutes: int = 30, description: str = "") -> Optional[str]:
        """Create a Google Calendar event."""
        try:
            service = self._get_service()
            start_dt = self._parse_datetime(date, time)
            if not start_dt:
                return None

            end_dt = start_dt + timedelta(minutes=duration_minutes)

            event_body = {
                "summary": title,
                "description": description,
                "start": {"dateTime": start_dt.isoformat()},
                "end": {"dateTime": end_dt.isoformat()},
            }

            created = service.events().insert(calendarId="primary", body=event_body).execute()
            return created.get("htmlLink")

        except Exception as e:
            print(f"[CalendarService] add_event error: {e}")
            return None

    def get_todays_events(self) -> List[dict]:
        """Fetch today's events for the dashboard."""
        try:
            service = self._get_service()
            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=0)

            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=start_of_day.isoformat(),
                    timeMax=end_of_day.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            result = []
            for ev in events:
                result.append({
                    "title": ev.get("summary", "Untitled Event"),
                    "start": ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")),
                    "end": ev.get("end", {}).get("dateTime", ev.get("end", {}).get("date", "")),
                    "link": ev.get("htmlLink", ""),
                    "location": ev.get("location", ""),
                })
            return result
        except Exception as e:
            print(f"[CalendarService] get_todays_events error: {e}")
            return []


# -- Module-level legacy wrappers for backward compatibility -------------------

def check_calendar_conflicts(access_token, refresh_token, date, time, duration=30):
    svc = CalendarService(access_token, refresh_token)
    return svc.check_conflicts(date, time, duration)

def add_calendar_event(access_token, refresh_token, title, date, time, duration=30, description=""):
    svc = CalendarService(access_token, refresh_token)
    return svc.add_event(title, date, time, duration, description)

def get_todays_events(access_token, refresh_token):
    svc = CalendarService(access_token, refresh_token)
    return svc.get_todays_events()

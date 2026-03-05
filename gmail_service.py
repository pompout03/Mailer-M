import os
import base64
import re
from email.utils import parseaddr
from typing import List, Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()


class GmailService:
    """
    A clean service class for interacting with the Gmail API.
    Handles authentication, token refresh, and email parsing.
    """

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.send",
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
        # Auto-refresh if the token is expired
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
                # Update stored token so the caller can persist the new one
                self.access_token = creds.token
            except Exception as e:
                print(f"[GmailService] Token refresh failed: {e}")
        return creds

    def _get_service(self):
        """Lazy-initialize the Gmail API client."""
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ── Public Methods ─────────────────────────────────────────────────────────

    def fetch_emails(self, n: int = 20, query: str = "") -> List[dict]:
        """
        Fetch the latest `n` emails matching an optional Gmail search `query`.
        Returns a list of parsed email dicts ready for Pydantic validation.
        """
        try:
            service = self._get_service()
            results = (
                service.users()
                .messages()
                .list(userId="me", maxResults=n, q=query)
                .execute()
            )
            messages = results.get("messages", [])

            email_list = []
            for msg in messages:
                parsed = self._fetch_and_parse(service, msg["id"])
                if parsed:
                    email_list.append(parsed)
            return email_list

        except Exception as e:
            print(f"[GmailService] fetch_emails error: {e}")
            return []

    def mark_as_read(self, message_id: str) -> bool:
        """Remove the UNREAD label from a Gmail message."""
        try:
            service = self._get_service()
            service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
            return True
        except Exception as e:
            print(f"[GmailService] mark_as_read error for {message_id}: {e}")
            return False

    # ── Private Helpers ────────────────────────────────────────────────────────

    def _fetch_and_parse(self, service, msg_id: str) -> Optional[dict]:
        """Fetch a single message and parse it into a dict."""
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            return self._parse_message(msg)
        except Exception as e:
            print(f"[GmailService] Error fetching message {msg_id}: {e}")
            return None

    def _parse_message(self, msg: dict) -> dict:
        """Extract all relevant fields from a raw Gmail message."""
        headers = msg.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers}

        raw_from = header_map.get("from", "Unknown")
        sender_name, sender_email = parseaddr(raw_from)
        if not sender_name:
            sender_name = sender_email.split("@")[0] if "@" in sender_email else raw_from

        subject = header_map.get("subject", "(No Subject)")
        date_str = header_map.get("date", "")
        snippet = msg.get("snippet", "")
        label_ids = msg.get("labelIds", [])
        is_read = "UNREAD" not in label_ids

        body = self._extract_body(msg.get("payload", {}))

        return {
            "message_id": msg["id"],
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
            "date_str": date_str,
            "body": body,
            "snippet": snippet,
            "is_read": is_read,
        }

    def _extract_body(self, payload: dict, prefer_plain: bool = True) -> str:
        """
        Recursively extract body text from a Gmail message payload.
        Prefers text/plain; falls back to text/html (stripped of tags).
        """
        mime_type = payload.get("mimeType", "")

        # Direct body (single-part message)
        if mime_type in ("text/plain", "text/html"):
            data = payload.get("body", {}).get("data", "")
            if data:
                text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                if mime_type == "text/plain":
                    return text
                else:
                    return self._strip_html(text)

        # Multi-part — recurse into parts
        parts = payload.get("parts", [])
        plain_body = ""
        html_body = ""
        for part in parts:
            result = self._extract_body(part, prefer_plain)
            if part.get("mimeType") == "text/plain" and result:
                plain_body = result
            elif part.get("mimeType", "").startswith("text/html") and result:
                html_body = result
            elif result and not plain_body:
                plain_body = result

        return plain_body or html_body

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags and collapse whitespace."""
        clean = re.sub(r"<[^>]+>", " ", html)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean


# ── Module-level convenience functions (kept for backward compat) ──────────────

def fetch_unread_emails(access_token: str, refresh_token: str) -> List[dict]:
    """Legacy wrapper — fetch unread emails only."""
    svc = GmailService(access_token, refresh_token)
    return svc.fetch_emails(n=20, query="is:unread")


def mark_as_read(access_token: str, refresh_token: str, message_id: str) -> bool:
    """Legacy wrapper — mark a single message as read."""
    svc = GmailService(access_token, refresh_token)
    return svc.mark_as_read(message_id)

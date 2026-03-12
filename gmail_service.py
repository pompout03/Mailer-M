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

        # Extract both plain text (for AI) and HTML (for display)
        body_plain, body_html = self._extract_body_both(msg.get("payload", {}))

        return {
            "message_id": msg["id"],
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
            "date_str": date_str,
            "body": body_plain,          # plain text for Gemini AI analysis
            "body_html": body_html,      # raw HTML for iframe display
            "snippet": snippet,
            "is_read": is_read,
        }

    def _extract_body_both(self, payload: dict):
        """
        Recursively extract both plain text and HTML body from a Gmail payload.
        Returns (plain_text, html_text) tuple.
        """
        mime_type = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")

        if mime_type == "text/plain" and data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            return text, ""

        if mime_type == "text/html" and data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            return self._strip_html(html), html

        # Multi-part — recurse and aggregate
        parts = payload.get("parts", [])
        plain_body = ""
        html_body = ""

        for part in parts:
            p, h = self._extract_body_both(part)
            if p and not plain_body:
                plain_body = p
            if h and not html_body:
                html_body = h

        # If we have HTML but still no plain, derive plain from HTML
        if html_body and not plain_body:
            plain_body = self._strip_html(html_body)

        return plain_body, html_body

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove HTML tags, URLs from links, and collapse whitespace."""
        # Remove entire <a href="...">...</a> blocks to avoid leaving raw URLs
        clean = re.sub(r'<a\s[^>]*>.*?</a>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
        # Remove inline image tags
        clean = re.sub(r'<img\s[^>]*>', ' ', clean, flags=re.IGNORECASE)
        # Remove all remaining HTML tags
        clean = re.sub(r"<[^>]+>", " ", clean)
        # Collapse whitespace
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
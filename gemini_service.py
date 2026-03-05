import os
import json
from google import genai
from google.genai import types
from typing import List
from dotenv import load_dotenv

load_dotenv()

# ── Configure Gemini (new google.genai SDK) ────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_MODEL_NAME = "gemini-2.0-flash"

# ── Default fallback response ──────────────────────────────────────────────────
_DEFAULT_ANALYSIS = {
    "summary": "Unable to analyze this email.",
    "category": "fyi",
    "meeting": {
        "detected": False,
        "title": "",
        "date": "",
        "time": "",
    },
    "action_items": [],
}

# ── Prompt Template ────────────────────────────────────────────────────────────
_PROMPT_TEMPLATE = """You are an AI executive assistant. Analyze the email below and respond ONLY with a single valid JSON object — no markdown, no code fences, no extra text. Your entire response must be parseable by json.loads().

Return this exact JSON structure:
{{
  "summary": "<2-sentence summary of the email>",
  "category": "<one of: urgent | meeting | action | newsletter | fyi>",
  "meeting": {{
    "detected": <true or false>,
    "title": "<meeting title or empty string>",
    "date": "<date if mentioned as YYYY-MM-DD, or empty string>",
    "time": "<time if mentioned as HH:MM, or empty string>"
  }},
  "action_items": ["<action item 1>", "<action item 2>"]
}}

Category rules:
- urgent: requires immediate attention, deadline, or critical issue
- meeting: contains a meeting invite, scheduling request, or calendar event
- action: requires a task or follow-up from the recipient
- newsletter: marketing email, digest, or announcement with no action needed
- fyi: informational email, no action required

Email to analyze:
Sender: {sender}
Subject: {subject}
Body:
{body}"""


def analyze_email(subject: str, sender: str, body: str) -> dict:
    """
    Send a single email to Gemini for analysis.
    Returns a dict with: summary, category, meeting, action_items.
    Falls back to _DEFAULT_ANALYSIS on any error.
    """
    if not _client:
        print("[GeminiService] GEMINI_API_KEY not set — returning default analysis.")
        return _DEFAULT_ANALYSIS.copy()

    # Truncate body to avoid token limits (keep first 3000 chars)
    truncated_body = body[:3000] if body else "(no body)"

    prompt = _PROMPT_TEMPLATE.format(
        sender=sender,
        subject=subject,
        body=truncated_body,
    )

    try:
        response = _client.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=512,
            ),
        )
        raw_text = response.text.strip()

        # Strip accidental markdown code fences if Gemini adds them
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        # Validate/fill missing keys with defaults
        result.setdefault("summary", _DEFAULT_ANALYSIS["summary"])
        result.setdefault("category", "fyi")
        result.setdefault("meeting", _DEFAULT_ANALYSIS["meeting"])
        result.setdefault("action_items", [])

        meeting = result["meeting"]
        meeting.setdefault("detected", False)
        meeting.setdefault("title", "")
        meeting.setdefault("date", "")
        meeting.setdefault("time", "")

        # Normalize category to allowed values
        allowed = {"urgent", "meeting", "action", "newsletter", "fyi"}
        if result["category"] not in allowed:
            result["category"] = "fyi"

        return result

    except json.JSONDecodeError as e:
        print(f"[GeminiService] JSON parse error: {e}")
        return _DEFAULT_ANALYSIS.copy()
    except Exception as e:
        print(f"[GeminiService] analyze_email error: {e}")
        return _DEFAULT_ANALYSIS.copy()


def analyze_emails_batch(emails: List[dict]) -> List[dict]:
    """
    Analyze a list of email dicts.
    Each dict must have keys: subject, sender_email (or sender), body.
    Returns a list of analysis dicts in the same order.
    """
    results = []
    for email in emails:
        subject = email.get("subject", "")
        sender = email.get("sender_email") or email.get("sender", "")
        body = email.get("body", "")
        analysis = analyze_email(subject=subject, sender=sender, body=body)
        results.append(analysis)
    return results

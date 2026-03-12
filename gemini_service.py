import os
import json
import copy
import asyncio
from google import genai
from google.genai import types
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# -- Configure Gemini (new google.genai SDK) ------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_MODEL_NAME = "gemini-2.0-flash-001"

# -- Default fallback response --------------------------------------------------
_DEFAULT_ANALYSIS = {
    "summary": "Unable to analyze this email.",
    "category": "fyi",
    "priority": "low",
    "needs_attention_now": False,
    "waiting": False,
    "meeting": {
        "detected": False,
        "title": "",
        "date": "",
        "time": "",
        "duration_minutes": 30,
    },
    "action_items": [],
    "form_detected": False,
    "form_description": "",
}

# -- Prompt Template ------------------------------------------------------------
_PROMPT_TEMPLATE = """You are an AI chief of staff for a busy professional. Analyze the email below and respond with a single JSON object.

Return this exact JSON structure:
{{
  "summary": "<2-sentence summary of the email>",
  "category": "<one of: urgent | meeting | action | form | newsletter | fyi>",
  "priority": "<one of: high | medium | low>",
  "needs_attention_now": <true or false>,
  "waiting": <true or false>,
  "meeting": {{
    "detected": <true or false>,
    "title": "<meeting title or empty string>",
    "date": "<date if mentioned as YYYY-MM-DD, or empty string>",
    "time": "<time if mentioned as HH:MM, or empty string>",
    "duration_minutes": <integer, default 30>
  }},
  "action_items": ["<action item 1>", "<action item 2>"],
  "form_detected": <true or false>,
  "form_description": "<what needs to be filled or signed, or empty string>"
}}

Category rules:
- urgent: requires immediate attention, hard deadline, or critical issue
- meeting: contains a meeting invite, scheduling request, or calendar event
- action: requires a task or follow-up from the recipient
- form: email contains a form, contract, or document that needs to be filled or signed
- newsletter: marketing email, digest, or announcement with no action needed
- fyi: informational email, no action required

Priority rules:
- high: urgent or time-sensitive, needs attention today
- medium: needs action soon (this week)
- low: no action needed or can wait

Email to analyze:
Sender: {sender}
Subject: {subject}
Body:
{body}"""


async def analyze_email_async(subject: str, sender: str, body: str) -> dict:
    """Analyze a single email using Gemini."""
    if not _client:
        print("[GeminiService] GEMINI_API_KEY not set.")
        return copy.deepcopy(_DEFAULT_ANALYSIS)

    truncated_body = body[:3000] if body else "(no body)"
    prompt = _PROMPT_TEMPLATE.format(sender=sender, subject=subject, body=truncated_body)

    try:
        response = await _client.aio.models.generate_content(
            model=_MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=600,
                response_mime_type="application/json",
            ),
        )

        raw = response.text.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        result = json.loads(raw)

        for key, val in _DEFAULT_ANALYSIS.items():
            if key not in result:
                result[key] = copy.deepcopy(val)
            elif isinstance(val, dict) and isinstance(result[key], dict):
                for subkey, subval in val.items():
                    result[key].setdefault(subkey, subval)

        if result.get("category") not in {"urgent", "meeting", "action", "form", "newsletter", "fyi"}:
            result["category"] = "fyi"
        if result.get("priority") not in {"high", "medium", "low"}:
            result["priority"] = "low"

        return result

    except json.JSONDecodeError as e:
        print(f"[GeminiService] JSON parse error: {e}")
        return copy.deepcopy(_DEFAULT_ANALYSIS)
    except Exception as e:
        print(f"[GeminiService] analyze_email error: {e}")
        return copy.deepcopy(_DEFAULT_ANALYSIS)


async def analyze_emails_batch(emails: List[dict]) -> List[dict]:
    """Analyze a list of emails in parallel."""
    tasks = []
    for email in emails:
        subject = email.get("subject", "")
        sender = email.get("sender_email") or email.get("sender", "")
        body = email.get("body", "")
        tasks.append(analyze_email_async(subject=subject, sender=sender, body=body))
    return await asyncio.gather(*tasks)


async def chat(message: str, history: Optional[List[dict]] = None) -> str:
    """
    Simple chat with Gemini — used to test the API is working.
    history: list of {"role": "user"|"model", "parts": [{"text": "..."}]}
    """
    if not _client:
        return "Error: GEMINI_API_KEY is not set in your .env file."

    try:
        contents = []

        if history:
            for turn in history:
                contents.append(turn)

        contents.append({"role": "user", "parts": [{"text": message}]})

        response = await _client.aio.models.generate_content(
            model=_MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.7,
                max_output_tokens=1000,
            ),
        )
        return response.text.strip()

    except Exception as e:
        print(f"[GeminiService] chat error: {e}")
        return f"Error contacting Gemini: {str(e)}"
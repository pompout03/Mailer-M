"""
routers/risc.py — Google Cross-Account Protection (RISC) endpoint.

Google sends signed Security Event Tokens (SETs) via HTTP POST to this
endpoint whenever a security event happens on a user's Google account
(e.g. account takeover, suspicious activity, token revocation, account disabled).

Steps:
  1. Fetch Google's RISC JWKS to verify the SET signature.
  2. Decode and validate the JWT claims.
  3. Look up the affected user in the DB and revoke their tokens / disable access.

Reference:
  https://developers.google.com/identity/risc/integrate
"""

import os
import json
import time
import httpx
import logging

from fastapi import APIRouter, Request, Response, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt, jwk, JWTError
from jose.utils import base64url_decode

from database import get_db
from models import User

logger = logging.getLogger("mailmind.risc")

router = APIRouter(prefix="/security", tags=["risc"])

# Google RISC JWKS endpoint — used to verify SET signatures
_GOOGLE_RISC_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_RISC_ISSUER   = "https://accounts.google.com"

# Cache the JWKS in memory so we don't fetch on every request
_jwks_cache: dict = {}
_jwks_cache_ts: float = 0.0
_JWKS_TTL = 3600  # 1 hour


async def _get_google_jwks() -> dict:
    global _jwks_cache, _jwks_cache_ts
    now = time.time()
    if _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
        return _jwks_cache
    async with httpx.AsyncClient() as client:
        resp = await client.get(_GOOGLE_RISC_JWKS_URI, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_ts = now
    return _jwks_cache


def _revoke_user_tokens(user: User, db: Session, reason: str) -> None:
    """Wipe stored OAuth tokens and log the event."""
    logger.warning(
        "[RISC] Revoking tokens for user %s — reason: %s", user.email, reason
    )
    user.google_access_token = None
    user.google_refresh_token = None
    db.commit()


@router.post(
    "/google-event",
    status_code=202,
    summary="Google RISC Security Event Token receiver",
)
async def receive_risc_event(request: Request, db: Session = Depends(get_db)):
    """
    Receives and processes Google Security Event Tokens (SETs).
    Google will POST a JWT here when a security event occurs on a user account.
    """
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty body")

    token = body.decode("utf-8").strip()

    # -- Decode header to get kid -----------------------------------------------
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        logger.error("[RISC] Could not decode JWT header: %s", e)
        raise HTTPException(status_code=400, detail="Invalid JWT")

    # -- Fetch Google JWKS and find matching key ---------------------------------
    try:
        jwks = await _get_google_jwks()
    except Exception as e:
        logger.error("[RISC] Failed to fetch Google JWKS: %s", e)
        raise HTTPException(status_code=503, detail="Could not fetch JWKS")

    kid = header.get("kid")
    matching_key = None
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            matching_key = key_data
            break

    if not matching_key:
        logger.error("[RISC] No matching JWKS key for kid=%s", kid)
        raise HTTPException(status_code=400, detail="Unknown signing key")

    # -- Verify and decode the SET -----------------------------------------------
    try:
        audience = os.getenv("GOOGLE_CLIENT_ID", "")
        claims = jwt.decode(
            token,
            matching_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=_GOOGLE_RISC_ISSUER,
            options={"verify_exp": False},  # SETs may not have exp per spec
        )
    except JWTError as e:
        logger.error("[RISC] JWT verification failed: %s", e)
        raise HTTPException(status_code=400, detail="JWT verification failed")

    logger.info("[RISC] Received valid SET: %s", json.dumps(claims))

    # -- Extract subject (Google subject identifier) ----------------------------
    # The `sub_id` or fallback `sub` claim identifies the affected Google account
    subject_id = claims.get("sub") or ""
    events = claims.get("events", {})

    # -- Look up user by Google subject or email --------------------------------
    # Google may include sub (subject) which maps to the Google account ID.
    # Since we store email, we search by email using the `email` claim if present.
    email = claims.get("email") or ""
    user = None
    if email:
        user = db.query(User).filter(User.email == email).first()

    if not user:
        # Nothing to act on — user not in our DB
        logger.info("[RISC] No local user found for subject=%s email=%s — ignoring", subject_id, email)
        return Response(status_code=202)

    # -- Handle each event type -------------------------------------------------
    handled = False

    # https://developers.google.com/identity/risc/app-integration-guide#event-types
    if "https://schemas.openid.net/secevent/risc/event-type/sessions-revoked" in events:
        _revoke_user_tokens(user, db, "sessions-revoked")
        handled = True

    if "https://schemas.openid.net/secevent/risc/event-type/tokens-revoked" in events:
        _revoke_user_tokens(user, db, "tokens-revoked")
        handled = True

    if "https://schemas.openid.net/secevent/risc/event-type/account-disabled" in events:
        _revoke_user_tokens(user, db, "account-disabled")
        handled = True

    if "https://schemas.openid.net/secevent/risc/event-type/account-enabled" in events:
        logger.info("[RISC] Account re-enabled for %s — no action required", user.email)
        handled = True

    if "https://schemas.openid.net/secevent/risc/event-type/account-purged" in events:
        # Hard delete the user from DB
        logger.warning("[RISC] Purging user %s from database.", user.email)
        db.delete(user)
        db.commit()
        handled = True

    if not handled:
        logger.info("[RISC] Unhandled event types: %s", list(events.keys()))

    return Response(status_code=202)

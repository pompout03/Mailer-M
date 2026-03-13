import os
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from dotenv import load_dotenv

# Ensure insecure transport is allowed for local development
# os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'

load_dotenv()

# ── OAuth Setup ────────────────────────────────────────────────────────────────
# authlib's starlette_client works perfectly with FastAPI
config_data = {
    'GOOGLE_CLIENT_ID': os.getenv('GOOGLE_CLIENT_ID', ''),
    'GOOGLE_CLIENT_SECRET': os.getenv('GOOGLE_CLIENT_SECRET', ''),
}
starlette_config = Config(environ=config_data)

oauth = OAuth(starlette_config)

oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        # Keep all scopes so existing refresh tokens stay valid
        'scope': (
            'openid email profile '
            'https://www.googleapis.com/auth/gmail.readonly '
            'https://www.googleapis.com/auth/gmail.modify '
            'https://www.googleapis.com/auth/gmail.send'
        ),
        # Request offline access so we get a refresh_token
        'access_type': 'offline',
        'prompt': 'consent',
    },
)


# ── Auth Dependency ────────────────────────────────────────────────────────────
def get_current_user(request: Request):
    """
    FastAPI dependency that returns the raw user_id string from the session.
    Raises HTTP 401 if the user is not logged in.
    Call as:  user_id: str = Depends(get_current_user)
    """
    # Debug: print session contents
    print("[DEBUG] Session in get_current_user:", request.session)
    user_id = request.session.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    return user_id


def get_current_user_id(request: Request) -> str:
    """Thin wrapper kept for backward compatibility."""
    return get_current_user(request)

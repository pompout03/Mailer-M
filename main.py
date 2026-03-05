import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import engine, get_db
import models
from models import User
import auth
from routers import emails, meetings, activity

load_dotenv()

# ── Database Bootstrap ─────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs background tasks on startup and cleans up on shutdown.
    Currently used for any periodic jobs (reserved for future use).
    """
    # Nothing blocking to start — keep this hook for future cron-style tasks
    print("[MailMind] Server started.")
    yield
    print("[MailMind] Server shutting down.")


# ── App Factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="MailMind",
    description="AI-powered Gmail assistant",
    version="1.0.0",
    lifespan=lifespan,
)

# Session middleware (must come before CORS so cookies are processed first)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "fallback-secret-key-change-me"),
)

# CORS — allow the frontend origin (localhost for dev, extend for prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Templates
os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(emails.router)
app.include_router(meetings.router)
app.include_router(activity.router)


# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.get("/login", tags=["auth"])
async def login(request: Request):
    """Redirect the user to Google's OAuth 2.0 consent screen."""
    try:
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
        return await auth.oauth.google.authorize_redirect(request, redirect_uri)
    except Exception as e:
        print(f"Login error: {e}")
        return HTMLResponse("OAuth error — check your GOOGLE_CLIENT_ID / CLIENT_SECRET in .env", status_code=500)


@app.get("/auth/callback", tags=["auth"])
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    """Handle the OAuth callback from Google, create/update user, set session."""
    try:
        token = await auth.oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            return HTMLResponse("Failed to fetch user info from Google.", status_code=400)

        email = user_info["email"]
        name = user_info.get("name", "User")
        picture = user_info.get("picture", "")

        # Upsert user
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, name=name, picture=picture)
            db.add(user)
            db.commit()
            db.refresh(user)

        # Always update tokens
        user.google_access_token = token.get("access_token")
        if token.get("refresh_token"):
            user.google_refresh_token = token.get("refresh_token")
        user.name = name
        user.picture = picture
        db.commit()

        # Debug: print session before setting user_id
        print("[DEBUG] Session before setting user_id:", request.session)
        request.session["user_id"] = user.id
        # Debug: print session after setting user_id
        print("[DEBUG] Session after setting user_id:", request.session)
        return RedirectResponse(url="/")
    except Exception as e:
        print(f"Auth callback error: {e}")
        return HTMLResponse(f"Authentication failed: {e}", status_code=400)
        return HTMLResponse(f"Authentication failed: {e}", status_code=400)


@app.get("/logout", tags=["auth"])
async def logout(request: Request):
    """Clear the session and redirect to login page."""
    request.session.clear()
    return RedirectResponse(url="/login_page")


# ── Frontend Routes ───────────────────────────────────────────────────────────
@app.get("/", tags=["frontend"])
async def home(request: Request, db: Session = Depends(get_db)):
    """Main dashboard — requires login."""
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login_page")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        request.session.clear()
        return RedirectResponse(url="/login_page")

    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/login_page", tags=["frontend"])
async def login_page(request: Request):
    """Render the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

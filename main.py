import os
import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from dotenv import load_dotenv

from database import engine, get_db
import models
from models import User
import auth
from routers import emails, meetings, activity
from gemini_service import chat as gemini_chat

load_dotenv()

# ── Database Bootstrap ─────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "fallback-secret-key-change-me"),
    same_site="lax",
    https_only=False,
    max_age=3600,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "https://accounts.google.com", "https://mailer-m.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

os.makedirs("templates", exist_ok=True)
templates = Jinja2Templates(directory="templates")

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(emails.router)
app.include_router(meetings.router)
app.include_router(activity.router)


# ── Chat (Gemini Test) ────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    history: Optional[List[dict]] = []

@app.post("/api/chat", tags=["chat"])
async def chat_endpoint(body: ChatMessage):
    """Chat with Gemini — used to verify the API is working."""
    reply = await gemini_chat(body.message, body.history)
    return {"reply": reply}


# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.get("/login", tags=["auth"])
async def login(request: Request):
    try:
        redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/callback")
        return await auth.oauth.google.authorize_redirect(request, redirect_uri)
    except Exception as e:
        print(f"Login error: {e}")
        return HTMLResponse("OAuth error — check your GOOGLE_CLIENT_ID / CLIENT_SECRET in .env", status_code=500)


@app.get("/auth/callback", tags=["auth"])
async def auth_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await auth.oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            return HTMLResponse("Failed to fetch user info from Google.", status_code=400)

        email = user_info["email"]
        name = user_info.get("name", "User")
        picture = user_info.get("picture", "")

        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, name=name, picture=picture)
            db.add(user)
            db.commit()
            db.refresh(user)

        user.google_access_token = token.get("access_token")
        if token.get("refresh_token"):
            user.google_refresh_token = token.get("refresh_token")
        user.name = name
        user.picture = picture
        db.commit()

        print("[DEBUG] Session before setting user_id:", request.session)
        request.session["user_id"] = user.id
        print("[DEBUG] Session after setting user_id:", request.session)
        return RedirectResponse(url="/")
    except Exception as e:
        print(f"Auth callback error: {e}")
        return HTMLResponse(f"Authentication failed: {e}", status_code=400)


@app.get("/logout", tags=["auth"])
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login_page")


# ── Frontend Routes ───────────────────────────────────────────────────────────
@app.get("/", tags=["frontend"])
async def home(request: Request, db: Session = Depends(get_db)):
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
    return templates.TemplateResponse("login.html", {"request": request})
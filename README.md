# MailMind 📬

**Your AI-powered Gmail executive assistant.** MailMind connects to your Gmail account, reads your inbox, and uses Google Gemini AI to automatically categorize, summarize, and surface action items — all in a beautiful dark-mode dashboard.

---

## ✨ Features

- **AI Email Analysis** — Gemini 1.5 Flash categorizes every email: `urgent`, `meeting`, `action`, `newsletter`, or `fyi`
- **Smart Summaries** — 2-sentence AI summary for every email, shown in the reading pane
- **Meeting Detection** — Automatically extracts meeting title, date, and time from emails
- **Action Item Checklist** — AI-extracted tasks shown as an interactive checklist
- **Filterable Inbox** — Tab-based filter by category with live counts
- **Interactive Calendar** — Google Calendar-style widget with event dots for detected meetings
- **Activity Timeline** — Live feed of urgent emails, action items, and upcoming meetings
- **Auto-Refresh** — Dashboard refreshes every 5 minutes to stay current
- **Google OAuth 2.0** — Secure sign-in with Google, no passwords stored

---

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11+) |
| Auth | Google OAuth 2.0 via Authlib |
| AI | Google Gemini 1.5 Flash |
| Gmail | Google Gmail API (read, modify) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| ORM | SQLAlchemy |
| Frontend | Vanilla HTML + CSS + JS |
| Fonts | Syne + DM Sans (Google Fonts) |
| Deployment | Render.com |

---

## ⚡ Local Setup

### 1. Clone and install

```bash
git clone <your-repo-url>
cd ds
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback
GEMINI_API_KEY=<from Google AI Studio — aistudio.google.com>
SECRET_KEY=<any random 32-char string>
DATABASE_URL=sqlite:///./prioritymail.db
```

### 3. Set up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Gmail API**
3. OAuth consent screen → Add your email as test user
4. Create **OAuth 2.0 Client ID** → Web Application
5. Add redirect URI: `http://localhost:8000/auth/callback`
6. Copy Client ID and Secret to `.env`

### 4. Get a Gemini API key

1. Visit [Google AI Studio](https://aistudio.google.com)
2. Click "Get API Key" → Create API key
3. Add to `.env` as `GEMINI_API_KEY`

### 5. Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) and sign in with Google.

---

## 🚀 Deploy to Render

1. Push your code to GitHub (without `.env`)
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect your repo — Render will detect `render.yaml`
4. Add environment variables in the Render dashboard:
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` → `https://your-app.onrender.com/auth/callback`
   - `GEMINI_API_KEY`
5. Deploy!

> **Note:** Add your Render URL as an authorized redirect URI in Google Cloud Console.

---

## 📁 Project Structure

```
ds/
├── routers/
│   ├── emails.py       # GET/POST /api/emails, /api/emails/sync, /stats
│   ├── meetings.py     # GET /api/meetings, /api/meetings/today
│   └── activity.py     # GET /api/activity
├── templates/
│   ├── index.html      # Full dashboard UI
│   └── login.html      # Login page
├── static/
│   ├── css/style.css   # Design system
│   └── js/app.js       # Client-side application
├── main.py             # FastAPI app, routes, middleware
├── auth.py             # Google OAuth setup + get_current_user()
├── models.py           # SQLAlchemy ORM + Pydantic schemas
├── database.py         # DB engine + session
├── gmail_service.py    # Gmail API client class
├── gemini_service.py   # Gemini AI analysis functions
└── requirements.txt
```

---

## 📄 License

MIT — free to use and modify.

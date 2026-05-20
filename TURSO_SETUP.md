# 🗄️ Free Online Database Setup — Turso + Render

This guide gets your NEMSU Lost & Found database **online and persistent for free**
using **Turso** (cloud SQLite) deployed on **Render**.

---

## Step 1 — Create a Free Turso Database

1. Go to **https://turso.tech** and click **Sign Up** (free)
2. Sign in with GitHub or email
3. In the dashboard click **"Create Database"**
4. Name it: `nemsu-laf`  |  Region: choose closest to Philippines (e.g. `sin` = Singapore)
5. Click **Create**

---

## Step 2 — Get Your Turso Credentials

After the database is created:

### Database URL
- Click your database → copy the **URL**
- It looks like: `libsql://nemsu-laf-yourname.turso.io`

### Auth Token
- Click **"Generate Token"** → copy the token
- It looks like: `eyJhbGciOiJFZERTQSJ9...`

⚠️ **Save both — you'll need them in the next step.**

---

## Step 3 — Deploy on Render (free)

1. Push this project to **GitHub** (create a repo if you haven't)
2. Go to **https://render.com** → Sign Up free
3. Click **New → Web Service**
4. Connect your GitHub repo
5. Fill in:
   - **Name:** `nemsu-lost-and-found`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`

---

## Step 4 — Set Environment Variables on Render

In your Render service → **Environment** tab, add these variables:

| Key | Value |
|-----|-------|
| `TURSO_DATABASE_URL` | `libsql://nemsu-laf-yourname.turso.io` |
| `TURSO_AUTH_TOKEN` | `eyJhbGciOiJFZERTQSJ9...` (your token) |
| `SECRET_KEY` | any random string e.g. `nemsu-secret-2024-xyz` |
| `GOOGLE_CLIENT_ID` | your Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | your Google OAuth client secret |
| `GOOGLE_REDIRECT_URI` | `https://your-app.onrender.com/auth/callback` |
| `APP_BASE_URL` | `https://your-app.onrender.com` |
| `PRODUCTION` | `true` |

---

## Step 5 — Deploy!

Click **Deploy** on Render. On first startup the app will:
1. Connect to your Turso database
2. Create all tables automatically
3. Load the admin account (`admin@nemsu.edu.ph` / `!admin123`)
4. Seed 100 dummy users + 500 items automatically

---

## ✅ Done — Your Database is Now Online

| Feature | Details |
|---------|---------|
| **Storage** | 500 MB free |
| **Row reads** | 1 billion/month free |
| **Persistence** | ✅ Data survives Render restarts |
| **Backups** | Turso dashboard has point-in-time restore |
| **Cost** | 🆓 Free forever on free tier |

---

## Troubleshooting

**"libsql_experimental not found"**
→ Make sure `libsql-experimental` is in `requirements.txt` and Render rebuilt.

**"Cannot connect to Turso"**
→ Double-check `TURSO_DATABASE_URL` starts with `libsql://` not `https://`

**App works but data resets**
→ You're still using local SQLite. Make sure BOTH env vars are set on Render.

**Test locally with Turso:**
```bash
export TURSO_DATABASE_URL="libsql://nemsu-laf-yourname.turso.io"
export TURSO_AUTH_TOKEN="your-token-here"
pip install libsql-experimental
python app.py
```

---

## Alternative: Run Locally (SQLite, no Turso needed)

Just run normally — the app auto-falls back to local SQLite:
```bash
pip install -r requirements.txt
python app.py
```
Data is stored at `/tmp/nemsu_laf.db` locally.

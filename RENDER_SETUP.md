# Render Deployment Setup

## Required Environment Variables
Go to your Render Dashboard → your service → **Environment** and set ALL of these:

| Variable | Value |
|---|---|
| `PRODUCTION` | `true` |
| `SECRET_KEY` | A fixed random string — generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `GOOGLE_CLIENT_ID` | From Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | From Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | `https://nemsu-lost-and-found-system.onrender.com/auth/callback` |

> ⚠️ **SECRET_KEY must be a FIXED value you set manually.**  
> Do NOT use `generateValue: true` — that creates a new key on every deploy, which  
> invalidates all user session cookies and logs everyone out.

---

## Google Cloud Console Setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. APIs & Services → Credentials → your OAuth 2.0 Client
3. Under **Authorized Redirect URIs**, add exactly:
   ```
   https://nemsu-lost-and-found-system.onrender.com/auth/callback
   ```
4. Save. Changes take a few minutes to propagate.

---

## Important: Free Tier Database Limitation

Render's free tier has an **ephemeral filesystem** — `/tmp` is wiped every time the  
service restarts or spins down (after ~15 minutes of inactivity).

This means **the SQLite database is lost on every restart**. The app handles this  
gracefully (users are asked to log in again via Google, and their record is re-created),  
but data like items and claims will be lost.

**For permanent data storage**, upgrade to a Render PostgreSQL database and update  
`models/database.py` to use `psycopg2` instead of `sqlite3`.

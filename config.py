"""
config.py - Application Configuration
"""

import os

# Load .env file automatically for local development.
# On Vercel/production, env vars are injected directly — dotenv is a no-op there.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; rely on real environment variables

IS_PRODUCTION = bool(os.environ.get("PRODUCTION"))


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "nemsu-laf-secret-key-2024")

    # Google OAuth - set these in environment variables, never hardcode
    GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    GOOGLE_REDIRECT_URI = os.environ.get(
        "GOOGLE_REDIRECT_URI",
        "https://nemsu-lost-and-found-system.onrender.com/auth/callback"
    )

    # Database
    TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN   = os.environ.get("TURSO_AUTH_TOKEN",   "")
    DATABASE_PATH      = os.environ.get("DATABASE_PATH", "/tmp/nemsu_laf.db")

    # Session
    SESSION_PERMANENT          = True
    PERMANENT_SESSION_LIFETIME = 86400
    SESSION_COOKIE_SECURE   = IS_PRODUCTION
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True

    # Domain restriction
    ALLOWED_EMAIL_DOMAIN = "nemsu.edu.ph"

    # Gmail Notifications
    GMAIL_SENDER_EMAIL  = os.environ.get("GMAIL_SENDER_EMAIL",  "")
    GMAIL_REFRESH_TOKEN = os.environ.get("GMAIL_REFRESH_TOKEN", "")
    APP_BASE_URL        = os.environ.get("APP_BASE_URL", "")

    # ImgBB
    IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "")

    # Gemini AI
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

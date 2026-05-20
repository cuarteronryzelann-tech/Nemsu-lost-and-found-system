"""
controllers/ai_chatbot_controller.py - Gemini AI Chatbot Support
================================================================
Uses verified model strings from the Gemini API (May 2026).

Model chain (free tier, v1beta):
  gemini-2.5-flash-lite-preview-06-17  — newest lite, free preview
  gemini-2.5-flash                     — best free-tier model (15 RPM)
  gemini-1.5-flash                     — proven fallback (15 RPM)
  gemini-1.5-flash-8b-001              — versioned name for 8b model

All 404 errors on unknown model names are now caught and skipped.
"""

import os
import time
import random
import logging
import threading
import requests
from collections import deque
from flask import Blueprint, request, jsonify, session
from functools import wraps

logger = logging.getLogger(__name__)

ai_bp = Blueprint("ai", __name__, url_prefix="/ai")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Verified model strings — ordered best-first for the free tier.
# The code probes each one and skips any that return 404 (unknown/retired).
MODEL_CHAIN = [
    "gemini-2.5-flash-lite-preview-06-17",  # lightweight 2.5, free preview
    "gemini-2.5-flash",                     # best free-tier 2.5 model
    "gemini-1.5-flash",                     # reliable 1.5 fallback
    "gemini-1.5-flash-8b-001",              # smallest/fastest 1.5 variant
]

# Models confirmed 404 at runtime — skip without logging spam
_dead_models: set = set()

# ── Per-user rate limiter (10 req / 60 s) ──────────────────────────────────
_rl_lock   = threading.Lock()
_rl_store  = {}
_RL_WINDOW = 60
_RL_MAX    = 10

def _check_rate_limit(user_id) -> bool:
    now = time.time()
    with _rl_lock:
        dq = _rl_store.setdefault(user_id, deque())
        while dq and dq[0] < now - _RL_WINDOW:
            dq.popleft()
        if len(dq) >= _RL_MAX:
            return False
        dq.append(now)
        return True

# ── System prompt ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are NEMSU LAF Assistant — a friendly AI support chatbot for the NEMSU (North Eastern Mindanao State University) Lost and Found System.

Help users with:
- Reporting lost or found items (photo, location, description required)
- The claim process and how to provide proof of ownership
- Item categories: Electronics, Clothing, Accessories, Books/Documents, Bags, Keys, ID Cards, Others
- Item statuses: Pending (awaiting admin approval), Available (can be claimed), Claimed, Archived
- Claim statuses: Pending, Approved, Denied, Returned
- Login: NEMSU email (@nemsu.edu.ph) via Google only
- Chat & notifications features

Be concise (under 150 words), warm, and helpful. For non-system questions, redirect to campus security or the admin office."""

ADMIN_SYSTEM_PROMPT = """You are an AI assistant for the NEMSU Lost and Found System administrator panel.

You help admins with:
- Approving or denying item claims and guidance on evidence review
- Managing item statuses: Pending (awaiting approval), Available, Claimed, Archived
- Handling abuse reports: dismissing, warning users, or deleting items
- Disabling or re-enabling user accounts
- Reading analytics: total items, claims, active users, turnover rate
- Understanding the chat/messaging system between users
- Archiving old or unclaimed items
- Managing found items and lost item reports

Item categories: Electronics, Clothing, Accessories, Books/Documents, Bags, Keys, ID Cards, Others.
Claim statuses: Pending, Approved, Denied, Returned.

Be concise (under 180 words), professional, and action-oriented. Focus on admin workflows and system management."""

# ── Auth decorator ───────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Try ONE model, up to `retries` attempts on 429/503 ──────────────────
def _try_model(url: str, payload: dict, retries: int = 2):
    """
    Returns:
      (text,   "ok")       — success
      (None, "skip")       — 404 (model doesn't exist) or hard error → skip to next
      (None, "retry")      — 429/503 exhausted → try next model
    """
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=20)
        except requests.Timeout:
            logger.warning("Timeout %s attempt %d", url.split("/")[-1], attempt + 1)
            if attempt < retries - 1:
                time.sleep(1.2)
            continue
        except Exception as e:
            logger.error("Request exception: %s", e)
            return None, "skip"

        if resp.status_code == 200:
            try:
                data       = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    return None, "skip"
                c = candidates[0]
                if c.get("finishReason") == "SAFETY":
                    return ("I'm sorry, I can't respond to that. "
                            "Please ask about the NEMSU Lost & Found system."), "ok"
                parts = c.get("content", {}).get("parts", [])
                text  = " ".join(p.get("text", "") for p in parts).strip()
                if text:
                    return text, "ok"
            except Exception as e:
                logger.error("Parse error: %s", e)
            return None, "skip"

        if resp.status_code == 404:
            return None, "skip"   # model doesn't exist — move on immediately

        if resp.status_code in (429, 503):
            retry_after = resp.headers.get("Retry-After")
            wait = min(float(retry_after), 6.0) if retry_after else \
                   min(0.8 * (2 ** attempt) + random.uniform(0, 0.3), 6.0)
            model_name = url.split("/")[-1].split(":")[0]
            logger.warning("HTTP %d on %s attempt %d/%d — waiting %.1fs",
                           resp.status_code, model_name, attempt + 1, retries, wait)
            if attempt < retries - 1:
                time.sleep(wait)
            continue  # retry same model

        logger.error("HTTP %d on %s", resp.status_code, url.split("/")[-1])
        return None, "skip"   # other 4xx/5xx — don't retry

    return None, "retry"   # 429/503 retries exhausted → caller tries next model


# ── Walk the model chain ─────────────────────────────────────────────────
def _call_gemini(api_key: str, contents: list, system_prompt: str = None) -> str | None:
    prompt = system_prompt or SYSTEM_PROMPT
    payload = {
        "system_instruction": {"parts": [{"text": prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 350,
        },
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",  "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        ],
    }

    active_models = [m for m in MODEL_CHAIN if m not in _dead_models]
    if not active_models:
        logger.error("All models are dead — clearing dead set and retrying")
        _dead_models.clear()
        active_models = list(MODEL_CHAIN)

    for model in active_models:
        url   = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
        text, status = _try_model(url, payload, retries=2)

        if status == "ok":
            logger.debug("Gemini OK via %s", model)
            return text

        if status == "skip":
            logger.info("Skipping model %s (404 or hard error)", model)
            _dead_models.add(model)
            continue   # try next model immediately

        if status == "retry":
            logger.warning("Model %s rate-limited, trying next", model)
            continue   # try next model

    return None   # all models exhausted


# ── Flask route ──────────────────────────────────────────────────────────
@ai_bp.route("/chat", methods=["POST"])
@login_required
def chat():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return jsonify({
            "ok": True,
            "reply": "The AI assistant isn't configured yet. Ask your admin to set GEMINI_API_KEY."
        })

    user_id = session["user"]["id"]
    if not _check_rate_limit(user_id):
        return jsonify({
            "ok": True,
            "reply": "You're sending messages very quickly! Please wait a moment before trying again. 😊"
        })

    data         = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()[:800]
    history      = data.get("history") or []
    context      = data.get("context", "")

    # Use admin prompt if the caller sent context="admin" AND the session user is actually an admin
    is_admin_ctx = (context == "admin" and session["user"].get("role") == "admin")
    system_prompt = ADMIN_SYSTEM_PROMPT if is_admin_ctx else SYSTEM_PROMPT

    if not user_message:
        return jsonify({"ok": False, "error": "Message cannot be empty"}), 400

    # Build contents — keep last 6 turns to stay within token limits
    contents = []
    for turn in history[-6:]:
        role = "user" if turn.get("role") == "user" else "model"
        text = (turn.get("text") or "").strip()
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    reply = _call_gemini(api_key, contents, system_prompt)

    if reply:
        return jsonify({"ok": True, "reply": reply})

    return jsonify({
        "ok": True,
        "reply": ("I'm having trouble connecting right now. "
                  "Please try again in a few seconds, or contact the admin office directly. 🙏")
    })

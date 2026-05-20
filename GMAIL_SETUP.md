<!-- set up by ryzel ann cuarteron -->





# Gmail Chat Notification — Setup Guide

## What was added

When any user sends a chat message, the **recipient** now automatically receives
a formatted email notification (sent via Gmail SMTP) with:

- Sender's name
- Message preview (first 80 characters)
- A "View Conversation" button that links directly to the chat thread

Email failures are **silent** — they are logged but never break the chat flow.

---

## Files changed / added

| File | Change |
|------|--------|
| `utils/gmail_notify.py` | **NEW** — Gmail SMTP helper |
| `controllers/chat_controller.py` | Added `send_chat_notification()` call in the `send` route |
| `config.py` | Added `GMAIL_SENDER_EMAIL`, `GMAIL_APP_PASSWORD`, `APP_BASE_URL` config vars |
| `requirements.txt` | Added comments (no new pip packages — uses stdlib `smtplib`) |
| `templates/chat/inbox.html` | **Skeleton loading** added |
| `templates/chat/conversation.html` | **Skeleton loading** added |

---

## How to enable Gmail notifications

### Step 1 — Create / choose a Gmail account

Use a dedicated Gmail (e.g. `nemsu.lostfound@gmail.com`) for sending notifications.

### Step 2 — Generate a Gmail App Password

1. Sign in to the Gmail account.
2. Go to **myaccount.google.com → Security → 2-Step Verification**.
3. Enable 2-Step Verification if not already on.
4. Scroll down to **App Passwords**.
5. Choose **Mail** + **Other (custom name)** → type "NEMSU LAF" → **Generate**.
6. Copy the 16-character password shown (spaces are ignored).

### Step 3 — Set environment variables

#### Local development (.env or shell)

```bash
export GMAIL_SENDER_EMAIL="nemsu.lostfound@gmail.com"
export GMAIL_APP_PASSWORD="abcd efgh ijkl mnop"   # paste the 16-char code
export APP_BASE_URL="http://localhost:5000"        # optional but recommended
```

#### Render deployment

In your Render service → **Environment** tab, add:

| Key | Value |
|-----|-------|
| `GMAIL_SENDER_EMAIL` | `nemsu.lostfound@gmail.com` |
| `GMAIL_APP_PASSWORD` | `abcdefghijklmnop` |
| `APP_BASE_URL` | `https://your-app.onrender.com` |

### Step 4 — Deploy / restart

No code changes needed — just set the env vars and restart the server.

---

## Disable notifications

Leave `GMAIL_SENDER_EMAIL` or `GMAIL_APP_PASSWORD` unset (empty).
The system will log a warning and skip sending — nothing breaks.

---

## Skeleton loading

Both `inbox.html` and `conversation.html` now show animated placeholder skeletons
(shimmer effect) while the page content loads. The skeleton auto-hides after
**400–500 ms** (or when `DOMContentLoaded` fires, whichever is later), then
smoothly reveals the real content. No JavaScript libraries required.

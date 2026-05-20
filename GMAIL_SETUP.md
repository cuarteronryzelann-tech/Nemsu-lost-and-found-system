<!-- set up by ryzel ann cuarteron -->

# Gmail Notification — Setup Guide

## How it works

The app sends email notifications via the **Gmail REST API over HTTPS (port 443)**.
This avoids SMTP (port 587), which Render's free plan blocks on outbound connections.

Notifications are sent for:
- 💬 **New chat message** — recipient gets an email when they are offline
- 🔖 **Item claimed** — the found-item reporter is notified when someone claims their item
- 🔍 **Possible match** — a lost-item reporter is notified when a matching found item appears

Email failures are **silent** — logged but they never break the app flow.

---

## Required environment variables

| Variable | Description |
|---|---|
| `GMAIL_SENDER_EMAIL` | Gmail address used to send notifications (e.g. `nemsu.lostfound@gmail.com`) |
| `GMAIL_REFRESH_TOKEN` | OAuth2 refresh token for that Gmail account (see steps below) |
| `GOOGLE_CLIENT_ID` | Already set for Google login — reused here |
| `GOOGLE_CLIENT_SECRET` | Already set for Google login — reused here |
| `APP_BASE_URL` | *(optional)* Full base URL so email links work, e.g. `https://your-app.onrender.com` |

---

## How to get your `GMAIL_REFRESH_TOKEN`

### Step 1 — Enable the Gmail API

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Select the same project that has your Google OAuth credentials.
3. In the left menu go to **APIs & Services → Library**.
4. Search for **Gmail API** and click **Enable**.

### Step 2 — Add the Gmail send scope to your OAuth client

1. Go to **APIs & Services → OAuth consent screen**.
2. Under **Scopes**, click **Add or Remove Scopes**.
3. Add `https://www.googleapis.com/auth/gmail.send`.
4. Save.

### Step 3 — Generate the refresh token (one-time)

Run this in your terminal (requires Python + `requests`):

```bash
pip install requests
python3 - <<'PYEOF'
import urllib.parse, webbrowser

CLIENT_ID     = "YOUR_GOOGLE_CLIENT_ID"
REDIRECT_URI  = "urn:ietf:wg:oauth:2.0:oob"   # for desktop/manual flow
SCOPE         = "https://www.googleapis.com/auth/gmail.send"

url = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    f"&response_type=code"
    f"&scope={urllib.parse.quote(SCOPE)}"
    "&access_type=offline"
    "&prompt=consent"
)
print("Open this URL in the browser and sign in with your sender Gmail account:")
print(url)
PYEOF
```

4. Sign in with the **sender Gmail account** (e.g. `nemsu.lostfound@gmail.com`).
5. Copy the **authorization code** shown.

```bash
python3 - <<'PYEOF'
import requests

CLIENT_ID     = "YOUR_GOOGLE_CLIENT_ID"
CLIENT_SECRET = "YOUR_GOOGLE_CLIENT_SECRET"
REDIRECT_URI  = "urn:ietf:wg:oauth:2.0:oob"
CODE          = "PASTE_AUTH_CODE_HERE"

r = requests.post("https://oauth2.googleapis.com/token", data={
    "code":          CODE,
    "client_id":     CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri":  REDIRECT_URI,
    "grant_type":    "authorization_code",
})
print(r.json())
# Copy the value of "refresh_token" from the output
PYEOF
```

6. Copy the `refresh_token` value — this is your `GMAIL_REFRESH_TOKEN`.

---

## Setting environment variables

### Local development

```bash
export GMAIL_SENDER_EMAIL="nemsu.lostfound@gmail.com"
export GMAIL_REFRESH_TOKEN="1//0gABCDEF..."   # from step above
export GOOGLE_CLIENT_ID="73469908398-xxx.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="GOCSPX-xxx"
export APP_BASE_URL="http://localhost:5000"
```

Or add them to a `.env` file and load with `python-dotenv`.

### Render deployment

In your Render service → **Environment** tab, add:

| Key | Value |
|---|---|
| `GMAIL_SENDER_EMAIL` | `nemsu.lostfound@gmail.com` |
| `GMAIL_REFRESH_TOKEN` | `1//0gABCDEF...` |
| `APP_BASE_URL` | `https://your-app.onrender.com` |

`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are already set for OAuth login.

---

## Disable notifications

Leave `GMAIL_SENDER_EMAIL` or `GMAIL_REFRESH_TOKEN` unset (empty).
The system logs a warning and skips sending — nothing breaks.

---

## Files involved

| File | Purpose |
|---|---|
| `utils/gmail_notify.py` | Core sending logic (Gmail REST API, OAuth2) |
| `controllers/chat_controller.py` | Calls `send_chat_notification()` on new message |
| `controllers/user_controller.py` | Calls `send_match_notification()` and `send_claim_notification()` |
| `config.py` | Declares `GMAIL_SENDER_EMAIL`, `GMAIL_REFRESH_TOKEN`, `APP_BASE_URL` |

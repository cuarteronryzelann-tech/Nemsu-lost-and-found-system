"""
utils/gmail_notify.py - Gmail Email Notification via Gmail REST API
====================================================================
Sends email notifications using the Gmail API over HTTPS (port 443).
This works on Render's free plan because it avoids SMTP (port 587)
which Render blocks on outbound connections.

Required environment variables:
    GMAIL_SENDER_EMAIL    - the Gmail / Google Workspace address to send from
    GMAIL_REFRESH_TOKEN   - OAuth2 refresh token (see GMAIL_SETUP.md)
    GOOGLE_CLIENT_ID      - already in your config (reused here)
    GOOGLE_CLIENT_SECRET  - already in your config (reused here)

Optional:
    APP_BASE_URL          - base URL prefix for conversation links in emails
"""

import os
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
# NOTE: values are read at *call time* (not import time) via _cfg() so that
# environment variables set after the module is first imported are still
# picked up correctly (avoids silent empty-string failures on Render).

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL   = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _cfg(key: str) -> str:
    """Read an env var at call time, not import time."""
    return os.environ.get(key, "")


def _get_access_token() -> str | None:
    """Exchange the refresh token for a short-lived access token."""
    refresh_token = _cfg("GMAIL_REFRESH_TOKEN")

    # Support both Web app keys (GOOGLE_CLIENT_ID) and Desktop app keys (CLIENT_ID)
    client_id     = _cfg("GOOGLE_CLIENT_ID") or _cfg("CLIENT_ID")
    client_secret = _cfg("GOOGLE_CLIENT_SECRET") or _cfg("CLIENT_SECRET")

    if not all([refresh_token, client_id, client_secret]):
        logger.warning(
            "Gmail API: missing GMAIL_REFRESH_TOKEN, client_id, "
            "or client_secret — skipping notification."
        )
        return None

    resp = requests.post(GOOGLE_TOKEN_URL, data={
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
    }, timeout=10)

    if resp.status_code != 200:
        logger.error("Gmail token refresh failed: %s %s", resp.status_code, resp.text)
        return None

    return resp.json().get("access_token")


def _build_html_email(recipient_name: str, sender_name: str,
                      message_preview: str, conv_link: str,
                      app_base_url: str = "") -> str:
    """Return a formatted HTML email body."""
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    full_link = f"{app_base_url}{conv_link}" if app_base_url else conv_link

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#1a56db 0%,#1e40af 100%);
                     padding:28px 32px;text-align:center;">
            <div style="font-size:2rem;margin-bottom:6px;">💬</div>
            <h1 style="margin:0;color:#fff;font-size:1.3rem;font-weight:800;">New Message</h1>
            <p style="margin:4px 0 0;color:rgba(255,255,255,.75);font-size:.82rem;">
              NEMSU Lost &amp; Found System
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 12px;color:#1e293b;font-size:.95rem;">
              Hi <strong>{recipient_name}</strong>,
            </p>
            <p style="margin:0 0 20px;color:#475569;font-size:.9rem;line-height:1.6;">
              You have a new message from
              <strong style="color:#1a56db;">{sender_name}</strong>
              on the NEMSU Lost &amp; Found platform.
            </p>

            <!-- Message preview -->
            <div style="background:#f8fafc;border:1px solid #e2e8f0;
                        border-left:4px solid #1a56db;border-radius:10px;
                        padding:16px 18px;margin-bottom:24px;">
              <p style="margin:0 0 6px;font-size:.72rem;color:#94a3b8;
                         text-transform:uppercase;letter-spacing:.05em;font-weight:700;">
                Message Preview
              </p>
              <p style="margin:0;color:#1e293b;font-size:.92rem;line-height:1.55;
                         word-break:break-word;">
                {message_preview}
              </p>
            </div>

            <!-- CTA -->
            <div style="text-align:center;margin-bottom:28px;">
              <a href="{full_link}"
                 style="display:inline-block;background:#1a56db;color:#fff;
                        text-decoration:none;padding:12px 28px;border-radius:10px;
                        font-weight:700;font-size:.92rem;">
                View Conversation →
              </a>
            </div>

            <p style="margin:0;color:#94a3b8;font-size:.78rem;text-align:center;">
              Received on {now}
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e2e8f0;
                     padding:18px 32px;text-align:center;">
            <p style="margin:0;color:#94a3b8;font-size:.75rem;line-height:1.6;">
              Automated notification from <strong>NEMSU Lost &amp; Found</strong>.<br>
              Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def send_chat_notification(recipient_email: str,
                           recipient_name: str,
                           sender_name: str,
                           message_preview: str,
                           conv_link: str,
                           app_base_url: str = "") -> bool:
    """
    Send a Gmail notification via the Gmail REST API (HTTPS / port 443).
    Works on Render free plan — no SMTP required.

    Returns True on success, False on any failure (error is logged).
    """
    sender_email = _cfg("GMAIL_SENDER_EMAIL")
    if not sender_email:
        logger.warning("Gmail notification skipped: GMAIL_SENDER_EMAIL not set.")
        return False

    if not recipient_email:
        logger.warning("Gmail notification skipped: recipient_email is empty.")
        return False

    # ── 1. Get a fresh access token ────────────────────────────────────────
    access_token = _get_access_token()
    if not access_token:
        return False

    # ── 2. Build the MIME message ──────────────────────────────────────────
    subject   = f"💬 New message from {sender_name} | NEMSU Lost & Found"
    html_body = _build_html_email(
        recipient_name, sender_name,
        message_preview, conv_link, app_base_url
    )
    full_link = f"{app_base_url}{conv_link}" if app_base_url else conv_link
    text_body = (
        f"Hi {recipient_name},\n\n"
        f"You have a new message from {sender_name} on NEMSU Lost & Found.\n\n"
        f"Preview: {message_preview}\n\n"
        f"View conversation: {full_link}\n\n"
        f"-- NEMSU Lost & Found System (automated notification)"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"NEMSU Lost & Found <{sender_email}>"
    msg["To"]      = recipient_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # ── 3. Base64-encode the raw message (Gmail API requirement) ───────────
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    # ── 4. POST to Gmail API ───────────────────────────────────────────────
    try:
        resp = requests.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            json={"raw": raw},
            timeout=15,
        )

        if resp.status_code == 200:
            logger.info("Gmail notification sent to %s", recipient_email)
            return True
        else:
            logger.error(
                "Gmail API send failed: %s %s", resp.status_code, resp.text
            )
            return False

    except requests.RequestException as exc:
        logger.error("Gmail API request error: %s", exc)
        return False


def send_claim_notification(recipient_email: str,
                             recipient_name: str,
                             claimant_name: str,
                             item_name: str,
                             item_link: str,
                             app_base_url: str = "") -> bool:
    """Notify a found-item reporter that someone claimed their item."""
    sender_email = _cfg("GMAIL_SENDER_EMAIL")
    if not sender_email:
        return False
    if not recipient_email:
        return False
    access_token = _get_access_token()
    if not access_token:
        return False

    full_link = f"{app_base_url}{item_link}" if app_base_url else item_link
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    subject = f"🔖 Someone claimed your found item | NEMSU Lost & Found"
    html_body = f"""
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:600px;width:100%;">
        <tr>
          <td style="background:linear-gradient(135deg,#1a56db 0%,#1e40af 100%);padding:28px 32px;text-align:center;">
            <div style="font-size:2rem;margin-bottom:6px;">🔖</div>
            <h1 style="margin:0;color:#fff;font-size:1.3rem;font-weight:800;">Item Claimed!</h1>
            <p style="margin:4px 0 0;color:rgba(255,255,255,.75);font-size:.82rem;">NEMSU Lost &amp; Found System</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 12px;color:#1e293b;font-size:.95rem;">Hi <strong>{recipient_name}</strong>,</p>
            <p style="margin:0 0 20px;color:#475569;font-size:.9rem;line-height:1.6;">
              <strong style="color:#1a56db;">{claimant_name}</strong> has submitted a claim for your found item
              <strong>"{item_name}"</strong>.
            </p>
            <div style="text-align:center;margin-bottom:28px;">
              <a href="{full_link}" style="display:inline-block;background:#1a56db;color:#fff;text-decoration:none;padding:12px 28px;border-radius:10px;font-weight:700;font-size:.92rem;">View Item →</a>
            </div>
            <p style="margin:0;color:#94a3b8;font-size:.78rem;text-align:center;">Received on {now}</p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:18px 32px;text-align:center;">
            <p style="margin:0;color:#94a3b8;font-size:.75rem;">Automated notification from <strong>NEMSU Lost &amp; Found</strong>.</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    text_body = f"Hi {recipient_name},\n\n{claimant_name} has claimed your found item '{item_name}'.\n\nView item: {full_link}\n\n-- NEMSU Lost & Found"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"NEMSU Lost & Found <{sender_email}>"
    msg["To"] = recipient_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        resp = requests.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception as exc:
        logger.error("Claim notification error: %s", exc)
        return False


def send_match_notification(
    recipient_email: str,
    recipient_name: str,
    lost_item_name: str,
    found_item_name: str,
    found_item_id: int,
    app_base_url: str = "",
) -> bool:
    """
    Notify a user who reported a LOST item that a potentially matching
    FOUND item has just been posted on the system.

    Also works in reverse: when a lost item is posted, notify the reporter
    of a matching found item (caller swaps the labels as needed).

    Args:
        recipient_email  : Email address of the person to notify.
        recipient_name   : Full name of the person to notify.
        lost_item_name   : Name of the lost item they originally reported.
        found_item_name  : Name of the newly posted found item that matches.
        found_item_id    : Database ID of the found item (used to build link).
        app_base_url     : Base URL of the deployment (e.g. https://your-app.onrender.com).

    Returns:
        True on success, False on any failure (error is logged, never raised).
    """
    sender_email = _cfg("GMAIL_SENDER_EMAIL")
    if not sender_email:
        logger.warning("Match notification skipped: GMAIL_SENDER_EMAIL not set.")
        return False
    if not recipient_email:
        logger.warning("Match notification skipped: recipient_email is empty.")
        return False

    access_token = _get_access_token()
    if not access_token:
        return False

    item_link = f"{app_base_url}/item/{found_item_id}"
    now       = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    subject   = f"🔍 Possible match found for your lost item | NEMSU Lost & Found"

    html_body = f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(0,0,0,.10);max-width:600px;width:100%;">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#059669 0%,#065f46 100%);
                     padding:28px 32px;text-align:center;">
            <div style="font-size:2rem;margin-bottom:6px;">🔍</div>
            <h1 style="margin:0;color:#fff;font-size:1.3rem;font-weight:800;">Possible Match Found!</h1>
            <p style="margin:4px 0 0;color:rgba(255,255,255,.75);font-size:.82rem;">
              NEMSU Lost &amp; Found System
            </p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:32px;">
            <p style="margin:0 0 12px;color:#1e293b;font-size:.95rem;">
              Hi <strong>{recipient_name}</strong>,
            </p>
            <p style="margin:0 0 20px;color:#475569;font-size:.9rem;line-height:1.6;">
              Great news! A recently reported <strong>found item</strong> may match
              the lost item you reported. Here are the details:
            </p>

            <!-- Item comparison card -->
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;
                          margin-bottom:24px;">
              <tr>
                <td width="50%" valign="top"
                    style="padding:16px 18px;background:#fef2f2;
                           border-right:1px solid #e2e8f0;">
                  <p style="margin:0 0 4px;font-size:.70rem;color:#ef4444;
                             text-transform:uppercase;letter-spacing:.06em;font-weight:700;">
                    Your Lost Item
                  </p>
                  <p style="margin:0;color:#1e293b;font-size:.92rem;
                             font-weight:600;word-break:break-word;">
                    {lost_item_name}
                  </p>
                </td>
                <td width="50%" valign="top"
                    style="padding:16px 18px;background:#f0fdf4;">
                  <p style="margin:0 0 4px;font-size:.70rem;color:#059669;
                             text-transform:uppercase;letter-spacing:.06em;font-weight:700;">
                    Found Item
                  </p>
                  <p style="margin:0;color:#1e293b;font-size:.92rem;
                             font-weight:600;word-break:break-word;">
                    {found_item_name}
                  </p>
                </td>
              </tr>
            </table>

            <p style="margin:0 0 20px;color:#475569;font-size:.85rem;line-height:1.6;">
              Please review the found item and, if it looks like yours,
              you can submit a claim directly from the item page.
            </p>

            <!-- CTA -->
            <div style="text-align:center;margin-bottom:28px;">
              <a href="{item_link}"
                 style="display:inline-block;background:#059669;color:#fff;
                        text-decoration:none;padding:12px 28px;border-radius:10px;
                        font-weight:700;font-size:.92rem;">
                View Found Item →
              </a>
            </div>

            <p style="margin:0;color:#94a3b8;font-size:.78rem;text-align:center;">
              Notification sent on {now}
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;border-top:1px solid #e2e8f0;
                     padding:18px 32px;text-align:center;">
            <p style="margin:0;color:#94a3b8;font-size:.75rem;line-height:1.6;">
              Automated notification from <strong>NEMSU Lost &amp; Found</strong>.<br>
              Please do not reply to this email.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Hi {recipient_name},\n\n"
        f"A recently reported found item may match your lost item.\n\n"
        f"Your lost item : {lost_item_name}\n"
        f"Found item     : {found_item_name}\n\n"
        f"View it here   : {item_link}\n\n"
        f"If it looks like yours, you can submit a claim from the item page.\n\n"
        f"-- NEMSU Lost & Found System (automated notification)"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"NEMSU Lost & Found <{sender_email}>"
    msg["To"]      = recipient_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    try:
        resp = requests.post(
            GMAIL_SEND_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
            },
            json={"raw": raw},
            timeout=15,
        )
        if resp.status_code == 200:
            logger.info("Match notification sent to %s", recipient_email)
            return True
        else:
            logger.error(
                "Match notification send failed: %s %s", resp.status_code, resp.text
            )
            return False
    except requests.RequestException as exc:
        logger.error("Match notification request error: %s", exc)
        return False
"""
generate_refresh_token.py
=========================
Run this ONCE on your local machine to get a Gmail refresh token.
The old "urn:ietf:wg:oauth:2.0:oob" flow is deprecated — this uses
a local HTTP server to capture the auth code automatically.

Usage:
    pip install requests
    python generate_refresh_token.py

Then paste the printed GMAIL_REFRESH_TOKEN into your Vercel env vars.
"""

import http.server
import threading
import urllib.parse
import webbrowser
import requests

# ── PASTE YOUR VALUES HERE ─────────────────────────────────────────────────
CLIENT_ID     = "73469908398-7gqrlae7rbah777usu3bv58i4jvu7m9d..."  # CLIENT_ID from Vercel
CLIENT_SECRET = "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"             # CLIENT_SECRET from Vercel
# ──────────────────────────────────────────────────────────────────────────

REDIRECT_URI  = "http://localhost:8080"
SCOPE         = "https://www.googleapis.com/auth/gmail.send"
auth_code     = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if auth_code:
            self.wfile.write(b"<h2>Authorization successful! You can close this tab.</h2>")
        else:
            self.wfile.write(b"<h2>Error: no code received.</h2>")

    def log_message(self, *args):
        pass  # silence request logs


def main():
    # Start local server to catch the redirect
    server = http.server.HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    # Build auth URL
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={urllib.parse.quote(SCOPE)}"
        f"&access_type=offline"
        f"&prompt=consent"
    )

    print("\n=== NEMSU Gmail Refresh Token Generator ===\n")
    print("Opening browser — sign in with your SENDER Gmail account")
    print("(the account that will send notifications, e.g. nemsu.lostfound@gmail.com)\n")
    print("If the browser doesn't open, paste this URL manually:")
    print(auth_url)
    print()
    webbrowser.open(auth_url)

    thread.join(timeout=120)

    if not auth_code:
        print("ERROR: Did not receive auth code within 2 minutes. Try again.")
        return

    print(f"Auth code received. Exchanging for tokens...\n")

    # Exchange code for tokens
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code":          auth_code,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri":  REDIRECT_URI,
        "grant_type":    "authorization_code",
    })

    data = resp.json()

    if "refresh_token" not in data:
        print("ERROR: No refresh_token in response.")
        print("Response:", data)
        print("\nCommon causes:")
        print("  - Gmail API not enabled in Google Cloud Console")
        print("  - gmail.send scope not added to OAuth consent screen")
        print("  - You did not click 'Allow' for the gmail.send permission")
        return

    print("=" * 60)
    print("SUCCESS! Add this to your Vercel environment variables:\n")
    print(f"  GMAIL_REFRESH_TOKEN = {data['refresh_token']}")
    print("=" * 60)
    print("\nAlso make sure these are set in Vercel:")
    print("  GMAIL_SENDER_EMAIL  = <the Gmail you just signed in with>")
    print("  GOOGLE_CLIENT_ID    = (already set)")
    print("  GOOGLE_CLIENT_SECRET= (already set)")
    print("  APP_BASE_URL        = https://nemsu-lost-and-found-system-three.vercel.app")


if __name__ == "__main__":
    main()

"""
app.py - Main Entry Point for NEMSU Lost and Found System (Optimized)
======================================================================
Initializes the Flask application, registers all blueprints (routes),
and starts the development server.

Optimization changes vs original:
  - Flask-Compress added: gzip-compresses HTML/JSON responses automatically,
    reducing bandwidth and improving perceived speed (especially on slow
    mobile networks like campus WiFi).
  - Static file cache header raised from 1 year to 1 year (unchanged, already good).
  - Added after_request hook to set Cache-Control: no-store on API JSON
    endpoints so browsers never cache stale badge counts.
  - Removed redundant import inside _serve_upload (mimetypes imported at top).
"""

import os
import mimetypes
from flask import Flask, request as flask_request
from config import Config
from controllers.auth_controller import auth_bp
from controllers.admin_controller import admin_bp
from controllers.user_controller import user_bp
from controllers.item_controller import item_bp
from controllers.chat_controller import chat_bp
from controllers.ai_chatbot_controller import ai_bp

if not os.environ.get("PRODUCTION"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # cache static files 1 year

    # ── Gzip compression ──────────────────────────────────────────────────
    # Compresses HTML, JSON, CSS responses — typically 60-80% size reduction.
    # Falls back gracefully if flask-compress is not installed.
    try:
        from flask_compress import Compress
        app.config['COMPRESS_MIMETYPES'] = [
            'text/html', 'text/css', 'application/json',
            'application/javascript', 'text/javascript',
        ]
        app.config['COMPRESS_LEVEL'] = 6      # balanced speed/ratio
        app.config['COMPRESS_MIN_SIZE'] = 500 # don't compress tiny responses
        Compress(app)
    except ImportError:
        pass  # optional — app works fine without it

    # ── Deferred DB init ─────────────────────────────────────────────────
    # On Vercel, app.py is imported once per cold start (module-level
    # ``app = create_app()``).  Running init_db() here fires a Turso
    # connection immediately on every cold start.  When many functions
    # spin up concurrently, that bursts past the free-tier connection
    # limit.  Moving it into before_request means it runs exactly once
    # per *process* (guarded by the _db_initialized flag in database.py)
    # and only after the runtime is fully ready.
    @app.before_request
    def _lazy_init_db():
        from models.database import init_db
        init_db()

    # ── Jinja2 globals ───────────────────────────────────────────────────
    def image_src(value, subfolder="items"):
        """Resolve stored image value to a usable <img src> URL.

        Matches NEMSU Marketplace img_url() logic:
        - ImgBB/external URL (starts with 'http') → return as-is
        - base64 data URI (starts with 'data:')   → return as-is
        - Bare filename in 'chat' subfolder        → return '' (legacy local
          uploads are gone on Vercel's ephemeral FS; avoids 404 requests)
        - Bare filename in other subfolders        → /uploads/<subfolder>/<filename>
        - None / empty                             → return ''
        """
        if not value:
            return ""
        if value.startswith("http") or value.startswith("data:"):
            return value
        # Legacy bare filename for chat — file no longer exists on Vercel.
        # Return '' so templates show the unavailable placeholder silently.
        if subfolder == "chat":
            return ""
        return f"/uploads/{subfolder}/{value}"
    app.jinja_env.globals["image_src"] = image_src

    # ── Global template context ───────────────────────────────────────────
    from flask import session as _session
    @app.context_processor
    def inject_finder_pending_count():
        """Provide pending claim count for nav badge on every page."""
        try:
            if "user" in _session:
                from models.claim_model import get_claims_for_finder
                claims = get_claims_for_finder(_session["user"]["id"])
                count = sum(1 for c in claims if c.get("status") == "pending_finder")
                return {"finder_pending_count": count}
        except Exception:
            pass
        return {"finder_pending_count": 0}

    # ── Cache-Control for JSON API endpoints ─────────────────────────────
    @app.after_request
    def set_cache_headers(response):
        if flask_request.path.startswith(('/user/notifications', '/chat/unread',
                                           '/user/heartbeat', '/chat/')):
            if response.content_type and 'json' in response.content_type:
                response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route("/healthz")
    def _healthz():
        return "ok", 200

    @app.route("/favicon.ico")
    @app.route("/favicon.png")
    def _favicon():
        from flask import send_from_directory
        return send_from_directory(
            os.path.join(app.root_path, "static", "img"),
            "logo.png",
            mimetype="image/png",
        )

    # ── Legacy /static/uploads/chat/<filename> intercept ─────────────────
    # Old messages stored bare filenames; browser requests hit Flask's static
    # handler at /static/uploads/chat/<filename>, which returns a real 404.
    # This route catches those requests first and returns a transparent GIF
    # (same as _serve_upload does for /uploads/…) so the log stays clean and
    # the onerror handlers in the template hide the broken <img> gracefully.
    _transparent_gif = (
        b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
        b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00"
        b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
    )

    @app.route("/static/uploads/chat/<filename>")
    def _serve_legacy_chat_image(filename):
        """Intercept legacy local-filename chat images before Flask's static handler 404s."""
        from flask import Response, send_from_directory
        if ".." in filename or "/" in filename:
            return Response("Bad Request", status=400)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        # Try to find the file in any known location (handles local dev)
        for folder in [
            os.path.join(app.root_path, "static", "uploads", "chat"),
            "/tmp/uploads/chat",
            "/tmp/chat_uploads",
        ]:
            if os.path.isfile(os.path.join(folder, filename)):
                return send_from_directory(folder, filename, mimetype=mime)
        # File gone (Vercel ephemeral FS) — return silent placeholder
        return Response(
            _transparent_gif,
            status=200,
            mimetype="image/gif",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.route("/uploads/<subfolder>/<filename>")
    def _serve_upload(subfolder, filename):
        from flask import send_from_directory, Response
        if ".." in subfolder or ".." in filename or "/" in filename:
            return Response("Bad Request", status=400)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Check 1: standard /tmp/uploads/<subfolder>/ path (items, profiles)
        tmp_path = os.path.join("/tmp", "uploads", subfolder)
        if os.path.isfile(os.path.join(tmp_path, filename)):
            return send_from_directory(tmp_path, filename, mimetype=mime)

        # Check 2: chat images — check both new path and legacy /tmp/chat_uploads
        if subfolder == "chat":
            for chat_tmp in ["/tmp/uploads/chat", "/tmp/chat_uploads"]:
                if os.path.isfile(os.path.join(chat_tmp, filename)):
                    return send_from_directory(chat_tmp, filename, mimetype=mime)

        # Check 3: real static folder (seed/fixture images shipped with repo)
        static_path = os.path.join(app.root_path, "static", "uploads", subfolder)
        if os.path.isfile(os.path.join(static_path, filename)):
            return send_from_directory(static_path, filename, mimetype=mime)

        # File not found — return a 1x1 transparent GIF placeholder instead of a
        # noisy 404. This handles chat images uploaded before ImgBB was integrated
        # whose files no longer exist on Vercel's ephemeral /tmp filesystem.
        # The onerror handlers in templates will hide the <img> anyway, but this
        # silences the server-side 404 log spam.
        _transparent_gif = (
            b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
            b"\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00"
            b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b"
        )
        return Response(
            _transparent_gif,
            status=200,
            mimetype="image/gif",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(item_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(ai_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
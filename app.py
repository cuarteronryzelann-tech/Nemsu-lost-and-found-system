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
from models.database import init_db
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

    init_db()

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

    @app.route("/static/uploads/<subfolder>/<filename>")
    def _serve_upload(subfolder, filename):
        from flask import send_from_directory, abort
        if ".." in subfolder or ".." in filename or "/" in filename:
            abort(400)
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Check 1: standard /tmp/uploads/<subfolder>/ path (items, profiles)
        tmp_path = os.path.join("/tmp", "uploads", subfolder)
        if os.path.isfile(os.path.join(tmp_path, filename)):
            return send_from_directory(tmp_path, filename, mimetype=mime)

        # Check 2: chat images are saved to /tmp/chat_uploads/ by chat_controller
        if subfolder == "chat":
            chat_tmp = "/tmp/chat_uploads"
            if os.path.isfile(os.path.join(chat_tmp, filename)):
                return send_from_directory(chat_tmp, filename, mimetype=mime)

        # Check 3: real static folder (seed/fixture images shipped with repo)
        static_path = os.path.join(app.root_path, "static", "uploads", subfolder)
        if os.path.isfile(os.path.join(static_path, filename)):
            return send_from_directory(static_path, filename, mimetype=mime)

        abort(404)

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

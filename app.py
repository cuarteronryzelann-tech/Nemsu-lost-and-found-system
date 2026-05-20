"""
app.py - Main Entry Point for NEMSU Lost and Found System
==========================================================
Initializes the Flask application, registers all blueprints (routes),
and starts the development server.
"""

import os
from flask import Flask
from config import Config
from models.database import init_db
from controllers.auth_controller import auth_bp
from controllers.admin_controller import admin_bp
from controllers.user_controller import user_bp
from controllers.item_controller import item_bp
from controllers.chat_controller import chat_bp
from controllers.ai_chatbot_controller import ai_bp

# Allow OAuth over plain HTTP only in local development.
# On Render (PRODUCTION=true), this is NOT set — HTTPS is used instead.
if not os.environ.get("PRODUCTION"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"


def create_app():
    """
    Application factory function.
    Creates and configures the Flask app instance,
    registers blueprints, and initializes the database.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000  # cache static files 1 year

    # Flask uses signed-cookie sessions by default (no filesystem needed)
    # This is reliable on Render's ephemeral filesystem environment.

    # Initialize the database (create tables if not exist)
    init_db()

    # Health-check endpoint — Render pings this to confirm the app is alive.
    @app.route("/healthz")
    def _healthz():
        return "ok", 200

    # Favicon routes — browsers request these automatically; serve the logo
    # so Vercel never logs a 404 for /favicon.ico or /favicon.png.
    @app.route("/favicon.ico")
    @app.route("/favicon.png")
    def _favicon():
        from flask import send_from_directory
        return send_from_directory(
            os.path.join(app.root_path, "static", "img"),
            "logo.png",
            mimetype="image/png",
        )

    # On Vercel the filesystem is read-only except /tmp, so uploaded files are
    # saved to /tmp/uploads/<subfolder>/<filename> (see save_upload() in
    # user_controller.py).  Flask's built-in static file handler only serves
    # files under the static/ folder, so user-uploaded images result in 404s
    # unless we add a dedicated route that reads from /tmp.
    @app.route("/static/uploads/<subfolder>/<filename>")
    def _serve_upload(subfolder, filename):
        from flask import send_from_directory, abort
        import mimetypes
        # Security: reject path traversal attempts
        if ".." in subfolder or ".." in filename or "/" in filename:
            abort(400)
        tmp_path = os.path.join("/tmp", "uploads", subfolder)
        full_path = os.path.join(tmp_path, filename)
        if os.path.isfile(full_path):
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return send_from_directory(tmp_path, filename, mimetype=mime)
        # Fall back to the real static folder (for seed/fixture images)
        static_path = os.path.join(app.root_path, "static", "uploads", subfolder)
        static_full = os.path.join(static_path, filename)
        if os.path.isfile(static_full):
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return send_from_directory(static_path, filename, mimetype=mime)
        abort(404)

    # Register blueprints
    app.register_blueprint(auth_bp)    # login / logout / OAuth
    app.register_blueprint(admin_bp)   # admin routes
    app.register_blueprint(user_bp)    # student routes
    app.register_blueprint(item_bp)    # shared item routes
    app.register_blueprint(chat_bp)    # chat / messaging
    app.register_blueprint(ai_bp)      # AI chatbot (Gemini)

    return app


# Create app at module level so gunicorn can find it
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
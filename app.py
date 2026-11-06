"""
app.py – CivicAI Flask Application
Phase 2: Citizen submission + admin dashboard.

Run:
    python app.py
    OR
    flask --app app run --debug
"""

import os
import logging
from flask import Flask, redirect, url_for, send_from_directory, abort

import database as db
from config import (
    SECRET_KEY, DEBUG, HOST, PORT,
    UPLOAD_DIR, BASE_DIR,
    ADMIN_AUTH_MODE, ADMIN_PASSWORD,
)
from routes.submit import submit_bp
from routes.admin  import admin_bp

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Application factory ───────────────────────────────────────────────────────

def _validate_admin_auth_config(auth_mode: str, admin_password: str) -> None:
    """
    Validate admin authentication configuration at startup.

    Raises RuntimeError if the configuration is unsafe or incomplete:
      - "password" mode requires a non-empty CIVICAI_ADMIN_PASSWORD.
      - Unknown auth modes are rejected.

    This function is called before the app starts accepting requests so that
    misconfigurations surface immediately rather than silently falling through.
    """
    valid_modes = {"open", "password", "disabled"}
    if auth_mode not in valid_modes:
        raise RuntimeError(
            f"Invalid CIVICAI_ADMIN_AUTH_MODE '{auth_mode}'. "
            f"Must be one of: {', '.join(sorted(valid_modes))}."
        )
    if auth_mode == "password" and not admin_password:
        raise RuntimeError(
            "CIVICAI_ADMIN_AUTH_MODE is 'password' but CIVICAI_ADMIN_PASSWORD "
            "is not set.  Set the environment variable before starting the server."
        )


def create_app(
    admin_auth_mode: str | None = None,
    admin_password:  str | None = None,
) -> Flask:
    """
    Create and configure the Flask application.

    Parameters
    ----------
    admin_auth_mode:
        Override ``config.ADMIN_AUTH_MODE`` (useful in tests).
    admin_password:
        Override ``config.ADMIN_PASSWORD`` (useful in tests).
    """
    # Resolve effective auth settings (caller overrides > env/config defaults)
    effective_mode     = admin_auth_mode if admin_auth_mode is not None else ADMIN_AUTH_MODE
    effective_password = admin_password  if admin_password  is not None else ADMIN_PASSWORD

    app = Flask(
        __name__,
        template_folder=os.path.join(BASE_DIR, "templates"),
        static_folder=os.path.join(BASE_DIR, "static"),
    )
    app.secret_key = SECRET_KEY

    # Persist auth settings so the blueprint can read them at request time
    app.config["ADMIN_AUTH_MODE"] = effective_mode
    app.config["ADMIN_PASSWORD"]  = effective_password

    # ── CSRF: lightweight token via session ───────────────────────────
    # Full WTForms CSRF is Phase 3+. We inject a simple session token here
    # to satisfy the template {{ csrf_token() }} call.
    from secrets import token_hex
    from flask import session

    @app.before_request
    def _ensure_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = token_hex(32)

    @app.template_global()
    def csrf_token():
        from flask import session
        return session.get("csrf_token", "")

    # ── Startup validation (fail closed) ─────────────────────────────
    # Skip in TESTING mode so unit tests can construct minimal apps freely.
    if not app.config.get("TESTING"):
        _validate_admin_auth_config(effective_mode, effective_password)

    # ── Blueprints ────────────────────────────────────────────────────
    app.register_blueprint(submit_bp)
    app.register_blueprint(admin_bp)

    # ── Home redirect ─────────────────────────────────────────────────
    @app.route("/")
    def index():
        # Render the new landing page instead of redirecting directly to the complaint form
        from flask import render_template
        return render_template("home.html")

    # ── Upload serving (images) ───────────────────────────────────────
    @app.route("/uploads/<path:filename>")
    def serve_upload(filename):
        """Serve uploaded complaint images securely."""
        # Prevent path traversal: only basename is stored in DB
        safe_name = os.path.basename(filename)
        if not os.path.isfile(os.path.join(UPLOAD_DIR, safe_name)):
            abort(404)
        return send_from_directory(UPLOAD_DIR, safe_name)

    # ── 404 / 500 handlers ────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        return render_template("errors/500.html"), 500

    # ── Ensure DB is ready ────────────────────────────────────────────
    with app.app_context():
        db.init_db()
        db.seed_departments()

    return app


# ── Entry point ───────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    logger.info("Starting CivicAI on http://%s:%d", HOST, PORT)
    app.run(host=HOST, port=PORT, debug=DEBUG)

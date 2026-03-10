"""
Flask application factory for JobHunter.
Initializes the Flask app with configuration and registers blueprints.
"""

import json
import secrets
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, g, session, redirect, url_for, flash, request, render_template
from flask_bcrypt import Bcrypt
from flask_mail import Mail
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config

# Module-level extension instances (initialized with app in create_app)
bcrypt = Bcrypt()
mail = Mail()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=[])

# ── Error monitoring state (in-memory rate-limit cache) ───────────────────────
# key: (url_path, exc_type_name) → datetime of last alert email sent
_error_alert_cache: dict = {}
_error_alert_lock = threading.Lock()


def create_app(config_class=Config):
    """
    Create and configure the Flask application.

    Args:
        config_class: Configuration class to use (default: Config)

    Returns:
        Flask application instance
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # ── Proxy fix: trust one level of X-Forwarded-* (Nginx → Gunicorn) ──────
    # Required so request.remote_addr reflects the client IP (not Nginx loopback),
    # which makes per-IP rate limiting and security log IPs accurate.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Create log directory (fallback to data/ if /var/log/jobhunter not writable) ─
    from config import LOG_DIR, DATA_DIR as _DATA_DIR
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Typically on Windows dev — fall back to data/
        app.config["ERROR_LOG_PATH"] = str(_DATA_DIR / "errors.log")
        app.config["SECURITY_LOG_PATH"] = str(_DATA_DIR / "security.log")

    # Initialize extensions
    bcrypt.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # ── Maintenance mode ────────────────────────────────────────────────────
    # Touch /home/ubuntu/JobHunter/maintenance_on (prod) or data/maintenance_on
    # (dev) to enable.  Remove the file to disable.
    _maintenance_prod = Path("/home/ubuntu/JobHunter/maintenance_on")
    _maintenance_dev = Path(__file__).resolve().parent.parent / "data" / "maintenance_on"

    @app.before_request
    def _check_maintenance():
        if _maintenance_prod.exists() or _maintenance_dev.exists():
            if request.path.startswith("/static") or request.path == "/health":
                return None
            return render_template("maintenance.html"), 503

    # ── Per-request CSP nonce ────────────────────────────────────────────────
    @app.before_request
    def _generate_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def _inject_csp_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    # ── Enforce mandatory 2FA ────────────────────────────────────────────────
    _2FA_EXEMPT_ENDPOINTS = {
        "main.account", "main.account_setup_2fa", "main.account_confirm_2fa",
        "main.account_disable_2fa", "main.account_delete",
        "main.logout", "main.login", "main.login_2fa", "main.register",
        "main.register_pending", "main.confirm_email", "main.resend_confirmation",
        "main.landing", "main.faq", "main.cgu",
        "main.confidentialite", "main.mentions_legales",
        "main.forgot_password",
        "static",
    }

    @app.before_request
    def _enforce_mandatory_2fa():
        # Only check authenticated users with a user_id in session
        user_id = session.get("user_id")
        if not user_id:
            return
        # Allow exempt routes (account, 2FA setup, logout, static)
        endpoint = request.endpoint or ""
        if endpoint in _2FA_EXEMPT_ENDPOINTS or endpoint.startswith("static"):
            return
        # Check totp_enabled from DB
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user and not user.totp_enabled:
                flash("Pour la sécurité de votre compte, l'activation de l'A2F est obligatoire.", "warning")
                return redirect(url_for("main.account"))
        finally:
            db.close()

    # ── Security headers ─────────────────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if app.config.get("ENV") == "production" or app.config.get("FLASK_ENV") == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP with per-request nonce for inline scripts/styles.
        # Chart.js is loaded from jsDelivr CDN (stats page).
        nonce = getattr(g, "csp_nonce", "")
        nonce_src = f"'nonce-{nonce}'" if nonce else "'unsafe-inline'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"script-src 'self' {nonce_src} https://cdn.jsdelivr.net; "
            f"style-src 'self' {nonce_src}; "
            "img-src 'self' data:; "
            "font-src 'self';"
        )
        return response

    # Import and register routes
    from app import routes
    app.register_blueprint(routes.bp)

    # Initialise the security event logger
    routes._init_security_logger(app.config.get("SECURITY_LOG_PATH", "data/security.log"))

    # ── Startup guard: refuse to start if no admin user exists in DB ─────────
    with app.app_context():
        try:
            from app.database import SessionLocal
            from app.models import User
            db = SessionLocal()
            try:
                admin_count = db.query(User).filter(
                    User.role == "admin", User.is_active == True
                ).count()
            finally:
                db.close()
            if admin_count == 0:
                import sys
                print(
                    "[SECURITY] No active admin user found in the database.\n"
                    "           Create an admin account before running the application:\n"
                    "             python create_admin.py\n"
                    "           Refusing to start.",
                    file=sys.stderr,
                )
                sys.exit(1)
        except SystemExit:
            raise
        except Exception:
            pass  # DB not initialised yet (first run) — let init_db() handle it

    # ── Custom error pages ──────────────────────────────────────────────────
    from werkzeug.exceptions import HTTPException

    @app.errorhandler(404)
    def page_not_found(exc):
        from flask import render_template as _rt
        return _rt("404.html"), 404

    # ── 500 / unhandled-exception monitoring ─────────────────────────────────

    @app.errorhandler(Exception)
    def handle_unhandled_exception(exc):
        # Let Werkzeug handle normal HTTP errors (403, 400, …) unchanged
        # (404 is handled above by its own handler)
        if isinstance(exc, HTTPException):
            return exc

        from flask import request as _req, session as _sess, render_template as _rt

        exc_tb   = traceback.format_exc()
        url      = _req.url
        method   = _req.method
        user_id  = _sess.get("user_id")
        exc_type = type(exc).__name__
        ts       = datetime.utcnow().isoformat(timespec="seconds")

        # 1. Append JSON entry to data/errors.log
        try:
            log_path = Path(app.config.get("ERROR_LOG_PATH", "data/errors.log"))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = json.dumps(
                {
                    "ts": ts,
                    "url": url,
                    "method": method,
                    "user_id": user_id,
                    "exc_type": exc_type,
                    "traceback": exc_tb,
                },
                ensure_ascii=False,
            )
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except Exception:
            pass  # never crash inside an error handler

        # 2. Rate-limited alert email (max 1 per unique url+exc_type per hour)
        admin_email = app.config.get("ADMIN_EMAIL")
        if admin_email:
            cache_key = (_req.path, exc_type)
            should_send = False
            with _error_alert_lock:
                last = _error_alert_cache.get(cache_key)
                if last is None or datetime.utcnow() - last > timedelta(hours=1):
                    _error_alert_cache[cache_key] = datetime.utcnow()
                    should_send = True

            if should_send:
                try:
                    from flask_mail import Message
                    msg = Message(
                        subject=f"🚨 MyJobHunter - Erreur 500 sur {_req.path}",
                        recipients=[admin_email],
                        body=(
                            f"URL      : {url}\n"
                            f"Méthode  : {method}\n"
                            f"User ID  : {user_id}\n"
                            f"Timestamp: {ts}\n\n"
                            f"Traceback:\n{exc_tb}"
                        ),
                    )
                    mail.send(msg)
                except Exception:
                    pass

        # 3. Return a clean 500 page
        try:
            return _rt("500.html"), 500
        except Exception:
            return "<h1>500 — Erreur interne du serveur</h1>", 500

    return app

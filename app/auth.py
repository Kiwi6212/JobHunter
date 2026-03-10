"""
Session-based authentication for JobHunter.
Roles: admin (full access + admin panel), user (write access, domain-scoped),
       viewer (read-only).
"""

from functools import wraps
from flask import session, redirect, url_for, request, jsonify


def get_current_user():
    """Return (username, role) for the logged-in user, or (None, None)."""
    username = session.get("username")
    role = session.get("role")
    if username and role:
        return username, role
    return None, None


def get_current_role():
    """Return the role of the current user ('admin', 'viewer', or None)."""
    return session.get("role")


def is_admin():
    return session.get("role") == "admin"


def is_viewer():
    return session.get("role") == "viewer"


def login_required(f):
    """
    Decorator that redirects unauthenticated users to /login.
    For AJAX requests (Accept: application/json), returns 401 JSON instead.
    Re-checks that the user account is still active on every request.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("main.login", next=request.path))
        # Re-verify that DB user is still active
        user_id = session.get("user_id")
        if user_id is not None:
            from app.database import SessionLocal
            from app.models import User
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.id == user_id).first()
                if not user or not user.is_active:
                    session.clear()
                    if request.is_json or request.headers.get("Accept") == "application/json":
                        return jsonify({"error": "Account disabled"}), 403
                    return redirect(url_for("main.login"))
            finally:
                db.close()
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """
    Decorator that blocks viewer-role (read-only) users from write endpoints.
    Both 'admin' and 'user' roles are allowed through.
    Returns 403 JSON for AJAX, or redirects to dashboard for HTML.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("main.login", next=request.path))
        if session.get("role") == "viewer":
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Accès en lecture seule"}), 403
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


def superadmin_required(f):
    """
    Decorator that requires the 'admin' role specifically.
    Used for the admin panel and user management endpoints.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("main.login", next=request.path))
        if session.get("role") != "admin":
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Admin access required"}), 403
            return redirect(url_for("main.dashboard"))
        return f(*args, **kwargs)
    return decorated


def check_credentials(username, password):
    """
    Validate username/password against DB users only (bcrypt).

    Returns:
        (role, user_id, domain_id) on success, or (None, None, None) on failure.
    """
    from app.database import SessionLocal
    from app.models import User
    from app import bcrypt
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        if user and bcrypt.check_password_hash(user.password_hash, password):
            if not user.is_active:
                return None, None, None  # Account disabled
            return user.role, user.id, user.domain_id
    except Exception:
        pass
    finally:
        db.close()
    return None, None, None

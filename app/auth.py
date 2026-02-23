"""
Simple session-based authentication for JobHunter.
Two roles: admin (full access) and viewer (read-only).
Credentials are loaded from .env via config.py.
"""

from functools import wraps
from flask import session, redirect, url_for, request, jsonify
from config import Config


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
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("username"):
            if request.is_json or request.headers.get("Accept") == "application/json":
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("main.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """
    Decorator that blocks viewer-role users from write endpoints.
    Returns 403 JSON for AJAX, or redirects to dashboard for HTML.
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
    Validate username/password against config.
    Returns the role string ('admin' or 'viewer') or None if invalid.
    """
    user = Config.USERS.get(username)
    if user and user["password"] == password:
        return user["role"]
    return None

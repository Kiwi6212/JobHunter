"""
Flask routes for JobHunter dashboard.
Handles all web interface endpoints and API endpoints for AJAX updates.
"""

import io
import json
import logging
import os
import time
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

# Cross-process file locking (Linux/Mac only; Windows falls back to thread lock)
try:
    import fcntl as _fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, send_file
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from werkzeug.utils import secure_filename

from app.database import SessionLocal
from app.models import Offer, Tracking, Domain, User, UserOffer
from app.auth import login_required, admin_required, superadmin_required, check_credentials, get_current_role
from app.services.filter_engine import normalize_text
from config import TARGET_COMPANIES, DATA_DIR
from app import limiter

# Create Blueprint
bp = Blueprint('main', __name__)

# ── Async CV matching task registry (file-backed, multi-worker safe) ──────────
# Tasks are stored in data/matching_tasks.json so all Gunicorn workers share state.
# File is keyed by str(user_id) or "_admin" for config/legacy admin (user_id=None).
_task_thread_lock = threading.Lock()  # intra-process thread safety


def _is_safe_redirect(url: str) -> bool:
    """Return True only if *url* is a relative path on the same host (no open redirect)."""
    if not url:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, url))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


# ── Auth routes ───────────────────────────────────────────────────────────────

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("20 per minute")
def login():
    """Login page. Redirects to dashboard if already authenticated."""
    if session.get("username"):
        return redirect(url_for("main.dashboard"))

    error = None
    if request.method == 'POST':
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role, user_id, domain_id = check_credentials(username, password)
        if role:
            # Regenerate session to prevent session fixation
            session.clear()
            session["username"] = username
            session["role"] = role
            session["user_id"] = user_id      # None for config (legacy) users
            session["domain_id"] = domain_id  # None for admin / config users
            next_url = request.args.get("next", "")
            if not _is_safe_redirect(next_url):
                next_url = url_for("main.dashboard")
            return redirect(next_url)
        error = "Identifiant ou mot de passe incorrect."

    return render_template("login.html", error=error)


@bp.route('/logout')
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for("main.login"))


@bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def register():
    """Self-registration: create a new user account linked to a domain."""
    if session.get("username"):
        return redirect(url_for("main.dashboard"))

    db = SessionLocal()
    try:
        domains = db.query(Domain).order_by(Domain.name).all()
        errors = []

        if request.method == 'POST':
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            domain_id_raw = request.form.get("domain_id", "").strip()

            if not username:
                errors.append("Nom d'utilisateur requis.")
            elif len(username) > 64:
                errors.append("Nom d'utilisateur trop long (max 64 caractères).")
            if not password:
                errors.append("Mot de passe requis.")
            elif len(password) < 8:
                errors.append("Mot de passe trop court (8 caractères minimum).")
            elif len(password) > 72:
                errors.append("Mot de passe trop long (72 caractères maximum).")
            if password and password != confirm:
                errors.append("Les mots de passe ne correspondent pas.")
            if not domain_id_raw:
                errors.append("Veuillez choisir un domaine.")

            if not errors:
                existing = db.query(User).filter(User.username == username).first()
                if existing:
                    errors.append("Ce nom d'utilisateur est déjà pris.")
                else:
                    from app import bcrypt
                    pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
                    new_user = User(
                        username=username,
                        password_hash=pw_hash,
                        role="user",
                        domain_id=int(domain_id_raw),
                    )
                    db.add(new_user)
                    db.commit()
                    return redirect(url_for("main.login"))

        return render_template("register.html", domains=domains, errors=errors)
    finally:
        db.close()


VALID_STATUSES = [
    'New', 'Applied', 'Followed up', 'Interview',
    'Accepted', 'Rejected', 'No response',
]

# CV storage paths
CV_DIR = DATA_DIR / "cv"
CV_TEXT_PATH = CV_DIR / "cv_text.txt"

# Task registry file (shared across all Gunicorn workers)
_TASKS_FILE = DATA_DIR / "matching_tasks.json"
_TASKS_LOCK_FILE = DATA_DIR / "matching_tasks.json.lock"


@contextmanager
def _tasks_lock_ctx():
    """Acquire thread lock + optional cross-process file lock (fcntl on Linux)."""
    with _task_thread_lock:
        if not _HAS_FCNTL:
            yield
            return
        try:
            _TASKS_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            lock_fh = open(_TASKS_LOCK_FILE, 'a')
            _fcntl.flock(lock_fh.fileno(), _fcntl.LOCK_EX)
            try:
                yield
            finally:
                _fcntl.flock(lock_fh.fileno(), _fcntl.LOCK_UN)
                lock_fh.close()
        except OSError:
            yield  # fallback: no file lock


def _read_tasks_raw() -> dict:
    """Read the tasks JSON file. Returns {} if missing or unreadable."""
    try:
        if _TASKS_FILE.exists():
            return json.loads(_TASKS_FILE.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_tasks_raw(data: dict) -> None:
    """Atomically write task data (write to .tmp then os.replace)."""
    _TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(_TASKS_FILE) + '.tmp')
    tmp.write_text(json.dumps(data, default=str), encoding='utf-8')
    os.replace(str(tmp), str(_TASKS_FILE))


def _load_task(user_id) -> dict | None:
    """Return the task state for user_id, or None if no task exists."""
    key = str(user_id) if user_id is not None else '_admin'
    with _tasks_lock_ctx():
        return _read_tasks_raw().get(key)


def _save_task(user_id, state: dict) -> None:
    """Persist task state for user_id to the shared JSON file."""
    key = str(user_id) if user_id is not None else '_admin'
    with _tasks_lock_ctx():
        data = _read_tasks_raw()
        data[key] = state
        _write_tasks_raw(data)


def _try_start_task(user_id, initial_state: dict) -> bool:
    """
    Atomic check-and-set: if no task is currently running for user_id,
    write initial_state and return True. Returns False if already running.
    """
    key = str(user_id) if user_id is not None else '_admin'
    with _tasks_lock_ctx():
        data = _read_tasks_raw()
        if data.get(key, {}).get('status') == 'running':
            return False
        data[key] = initial_state
        _write_tasks_raw(data)
    return True

# ── Document upload validation ────────────────────────────────────────────────
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB

# Exact MIME types accepted per extension (whitelist)
_ALLOWED_MIMES: dict[str, set[str]] = {
    '.pdf':  {'application/pdf', 'application/octet-stream'},
    '.docx': {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/zip',
        'application/octet-stream',
    },
    '.txt':  {'text/plain', 'application/octet-stream'},
}

# Always-rejected MIME types (execution risk / active content)
_BLOCKED_MIMES = {
    'text/html', 'application/xhtml+xml',
    'application/x-msdownload', 'application/x-executable',
    'application/x-sh', 'application/x-bat',
}


def _user_docs_dir():
    """Return the document directory scoped to the current user session."""
    user_id = session.get("user_id")
    folder = str(user_id) if user_id is not None else "legacy_admin"
    return DATA_DIR / "documents" / folder


@bp.route('/')
@bp.route('/dashboard')
@login_required
def dashboard():
    """
    Main dashboard view.
    Displays all job offers with their tracking status in an interactive table.
    """
    db = SessionLocal()
    user_id = session.get("user_id")
    domain_id = session.get("domain_id")
    try:
        # Filter offers by domain if the user has one
        query = db.query(Offer)
        if domain_id:
            query = query.filter(Offer.domain_id == domain_id)

        # Build user_offers_map: offer_id -> tracking object
        if user_id is None:
            # Config/legacy user (admin): load via Offer.tracking relationship
            offers = query.options(joinedload(Offer.tracking)).all()
            user_offers_map = {o.id: o.tracking for o in offers if o.tracking}
        else:
            # DB user: load UserOffer rows for this user
            offers = query.all()
            offer_ids = [o.id for o in offers]
            if offer_ids:
                user_offer_rows = db.query(UserOffer).filter(
                    UserOffer.user_id == user_id,
                    UserOffer.offer_id.in_(offer_ids),
                ).all()
            else:
                user_offer_rows = []
            user_offers_map = {uo.offer_id: uo for uo in user_offer_rows}

        total_offers = len(offers)

        # Stats — same fields regardless of tracking backend
        uo_values = list(user_offers_map.values())
        cv_sent_count = sum(1 for uo in uo_values if uo.cv_sent)
        follow_up_count = sum(1 for uo in uo_values if uo.follow_up_done)
        interview_count = sum(1 for uo in uo_values if uo.status == 'Interview')

        stats = {
            'total_offers': total_offers,
            'cv_sent': cv_sent_count,
            'follow_ups': follow_up_count,
            'interviews': interview_count,
        }

        # Collect unique sources for filter dropdown
        sources = sorted(set(o.source for o in offers))

        # Mark target company offers
        targets_norm = [normalize_text(c) for c in TARGET_COMPANIES]
        target_ids = set()
        for o in offers:
            co = normalize_text(o.company or "")
            for t in targets_norm:
                if t in co:
                    target_ids.add(o.id)
                    break

        has_cv = CV_TEXT_PATH.exists()
        cutoff_new = datetime.utcnow() - timedelta(hours=24)

        # Pass domain list to template only for admins (no domain scoping)
        admin_domains = []
        if not domain_id:
            admin_domains = db.query(Domain).order_by(Domain.name).all()

        return render_template(
            'dashboard.html',
            offers=offers,
            user_offers_map=user_offers_map,
            stats=stats,
            sources=sources,
            statuses=VALID_STATUSES,
            target_ids=target_ids,
            has_cv=has_cv,
            cutoff_new=cutoff_new,
            role=get_current_role(),
            username=session.get("username"),
            admin_domains=admin_domains,
        )
    finally:
        db.close()


@bp.route('/api/tracking/<int:offer_id>', methods=['PUT'])
@login_required
def update_tracking(offer_id):
    """
    AJAX endpoint to update tracking data for an offer.
    Accepts JSON with any combination of: status, cv_sent, follow_up_done,
    date_sent, follow_up_date, notes.
    DB users use UserOffer; config/legacy admin uses Tracking.
    """
    if session.get("role") == "viewer":
        return jsonify({"error": "Accès réservé"}), 403

    t_start = time.perf_counter()
    db = SessionLocal()
    user_id = session.get("user_id")
    try:
        t_q0 = time.perf_counter()
        if user_id is not None:
            tracking = db.query(UserOffer).filter(
                UserOffer.user_id == user_id,
                UserOffer.offer_id == offer_id,
            ).first()
            if not tracking:
                offer_exists = db.query(Offer.id).filter(Offer.id == offer_id).scalar()
                if not offer_exists:
                    return jsonify({'error': 'Offer not found'}), 404
                tracking = UserOffer(user_id=user_id, offer_id=offer_id, status='New')
                db.add(tracking)
        else:
            tracking = db.query(Tracking).filter(Tracking.offer_id == offer_id).first()
            if not tracking:
                offer_exists = db.query(Offer.id).filter(Offer.id == offer_id).scalar()
                if not offer_exists:
                    return jsonify({'error': 'Offer not found'}), 404
                tracking = Tracking(offer_id=offer_id, status='New')
                db.add(tracking)
        t_q1 = time.perf_counter()
        print(f"[DIAG] query tracking: {(t_q1 - t_q0) * 1000:.1f}ms")

        data = request.get_json()

        t_upd0 = time.perf_counter()
        if 'status' in data:
            if data['status'] in VALID_STATUSES:
                tracking.status = data['status']

        if 'cv_sent' in data:
            tracking.cv_sent = bool(data['cv_sent'])
            if tracking.cv_sent and not tracking.date_sent:
                tracking.date_sent = datetime.utcnow()
            elif not tracking.cv_sent:
                tracking.date_sent = None

        if 'follow_up_done' in data:
            tracking.follow_up_done = bool(data['follow_up_done'])
            if tracking.follow_up_done and not tracking.follow_up_date:
                tracking.follow_up_date = datetime.utcnow()
            elif not tracking.follow_up_done:
                tracking.follow_up_date = None

        if 'notes' in data:
            tracking.notes = data['notes'].strip() if data['notes'] else None

        tracking.updated_at = datetime.utcnow()
        t_upd1 = time.perf_counter()
        print(f"[DIAG] update fields: {(t_upd1 - t_upd0) * 1000:.1f}ms")

        t_c0 = time.perf_counter()
        db.commit()
        t_c1 = time.perf_counter()
        print(f"[DIAG] db.commit: {(t_c1 - t_c0) * 1000:.1f}ms")

        t_total = (time.perf_counter() - t_start) * 1000
        print(f"[DIAG] TOTAL server time for offer {offer_id}: {t_total:.1f}ms")

        return jsonify({
            'ok': True,
            'server_ms': round(t_total, 1),
            'tracking': {
                'status': tracking.status,
                'cv_sent': tracking.cv_sent,
                'follow_up_done': tracking.follow_up_done,
                'date_sent': tracking.date_sent.strftime('%Y-%m-%d') if tracking.date_sent else None,
                'follow_up_date': tracking.follow_up_date.strftime('%Y-%m-%d') if tracking.follow_up_date else None,
                'notes': tracking.notes,
            }
        })

    except Exception:
        db.rollback()
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        db.close()


@bp.route('/offer/<int:offer_id>')
@login_required
def offer_detail(offer_id):
    """Detailed view of a single job offer."""
    db = SessionLocal()
    user_id = session.get("user_id")
    domain_id = session.get("domain_id")
    try:
        offer = db.query(Offer).options(joinedload(Offer.tracking)).filter(
            Offer.id == offer_id
        ).first()
        if not offer:
            return "Offer not found", 404

        # Domain authorization: domain-scoped users may only view offers in their domain
        if domain_id and offer.domain_id and offer.domain_id != domain_id:
            return "Accès refusé", 403

        # Resolve per-user tracking object
        if user_id is not None:
            user_offer = db.query(UserOffer).filter(
                UserOffer.user_id == user_id,
                UserOffer.offer_id == offer_id,
            ).first()
        else:
            user_offer = offer.tracking  # config admin uses Tracking

        docs_dir = _user_docs_dir()
        docs_dir.mkdir(parents=True, exist_ok=True)
        doc_files = sorted(f.name for f in docs_dir.iterdir() if f.is_file())
        return render_template('offer_detail.html', offer=offer,
                               user_offer=user_offer,
                               doc_files=doc_files,
                               role=get_current_role(),
                               username=session.get("username"))
    finally:
        db.close()


@bp.route('/stats')
@login_required
def stats():
    """Statistics page with detailed metrics."""
    db = SessionLocal()
    user_id = session.get("user_id")
    domain_id = session.get("domain_id")
    try:
        offer_query = db.query(Offer)
        if domain_id:
            offer_query = offer_query.filter(Offer.domain_id == domain_id)
        total_offers = offer_query.count()

        def _uo():
            """Base query for the current user's tracking rows."""
            if user_id is not None:
                return db.query(UserOffer).filter(UserOffer.user_id == user_id)
            return db.query(Tracking)

        tracked_offers = _uo().count()
        cv_sent = _uo().filter(
            (UserOffer.cv_sent if user_id is not None else Tracking.cv_sent) == True
        ).count()
        follow_ups = _uo().filter(
            (UserOffer.follow_up_done if user_id is not None else Tracking.follow_up_done) == True
        ).count()

        status_counts = {}
        status_col = UserOffer.status if user_id is not None else Tracking.status
        for status in VALID_STATUSES:
            count = _uo().filter(status_col == status).count()
            status_counts[status] = count

        stats_data = {
            'total_offers': total_offers,
            'tracked': tracked_offers,
            'cv_sent': cv_sent,
            'follow_ups': follow_ups,
            'status_counts': status_counts,
        }

        # ── Chart data ────────────────────────────────────────────────
        # Offers per source (scoped by domain)
        source_rows = (
            offer_query.with_entities(Offer.source, func.count(Offer.id))
            .group_by(Offer.source)
            .order_by(func.count(Offer.id).desc())
            .all()
        )
        source_counts = {s: c for s, c in source_rows if s}

        # Top 10 companies by offer count (scoped by domain)
        company_rows = (
            offer_query.with_entities(Offer.company, func.count(Offer.id))
            .group_by(Offer.company)
            .order_by(func.count(Offer.id).desc())
            .limit(10)
            .all()
        )
        top_companies = {c: n for c, n in company_rows if c}

        # Score distribution in 10 equal buckets (0–10, 10–20, …, 90–100)
        score_rows = offer_query.with_entities(Offer.relevance_score).all()
        score_buckets = [0] * 10
        for (score,) in score_rows:
            s = float(score or 0)
            bucket = min(int(s // 10), 9)
            score_buckets[bucket] += 1

        # CV match score distribution (only when a CV has been uploaded)
        has_cv = CV_TEXT_PATH.exists()
        cv_score_buckets = [0] * 10
        if has_cv:
            if user_id is not None:
                # DB users: scores live in UserOffer.cv_match_score
                cv_rows = (
                    db.query(UserOffer.cv_match_score)
                    .filter(
                        UserOffer.user_id == user_id,
                        UserOffer.cv_match_score.isnot(None),
                    )
                    .all()
                )
            else:
                # Legacy admin: scores live in Offer.cv_match_score
                cv_rows = offer_query.with_entities(Offer.cv_match_score).filter(
                    Offer.cv_match_score.isnot(None)
                ).all()
            for (score,) in cv_rows:
                s = float(score or 0)
                bucket = min(int(s // 10), 9)
                cv_score_buckets[bucket] += 1

        chart_data = {
            'sources':         source_counts,
            'companies':       top_companies,
            'scores':          score_buckets,
            'statuses':        status_counts,
            'cv_scores':       cv_score_buckets,
        }

        return render_template(
            'stats.html',
            stats=stats_data,
            chart_data=chart_data,
            has_cv=has_cv,
            role=get_current_role(),
            username=session.get("username"),
        )
    finally:
        db.close()


def _persist_scores(db, user_id, offers, scores: dict) -> None:
    """
    Write cv_match_score values to the database.
    DB users  → upsert into UserOffer.cv_match_score (per-user).
    Legacy admin → write into Offer.cv_match_score.
    """
    if user_id is not None:
        offer_ids = list(scores.keys())
        existing_uos = {
            uo.offer_id: uo
            for uo in db.query(UserOffer).filter(
                UserOffer.user_id == user_id,
                UserOffer.offer_id.in_(offer_ids),
            ).all()
        }
        for offer_id, score in scores.items():
            if offer_id in existing_uos:
                existing_uos[offer_id].cv_match_score = score
            else:
                db.add(UserOffer(
                    user_id=user_id,
                    offer_id=offer_id,
                    cv_match_score=score,
                    status='New',
                ))
    else:
        offer_map = {o.id: o for o in offers}
        for offer_id, score in scores.items():
            if offer_id in offer_map:
                offer_map[offer_id].cv_match_score = score


def _build_offer_query(db, domain_id, user_id, force):
    """
    Build the SQLAlchemy query for offers that need scoring.
    Returns (query, skipped_count).
    """
    query = db.query(Offer)
    if domain_id:
        query = query.filter(Offer.domain_id == domain_id)

    if user_id is not None:
        if not force:
            already_sq = (
                db.query(UserOffer.offer_id)
                .filter(
                    UserOffer.user_id == user_id,
                    UserOffer.cv_match_score.isnot(None),
                )
                .subquery()
            )
            skipped = query.filter(Offer.id.in_(already_sq)).count()
            query = query.filter(~Offer.id.in_(already_sq))
        else:
            skipped = 0
    else:
        if not force:
            skipped = query.filter(Offer.cv_match_score.isnot(None)).count()
            query = query.filter(Offer.cv_match_score.is_(None))
        else:
            skipped = 0

    return query, skipped


def _cv_matching_worker(user_id, domain_id, method: str, force: bool) -> None:
    """
    Thread worker: runs CV matching and writes scores to DB.
    Persists progress to _TASKS_FILE after each batch so all workers can poll it.
    """
    db = SessionLocal()
    try:
        cv_text = CV_TEXT_PATH.read_text(encoding="utf-8")
        query, skipped = _build_offer_query(db, domain_id, user_id, force)
        offers = query.all()
        total = len(offers)
        _save_task(user_id, {
            'status': 'running', 'scored': 0, 'total': total,
            'skipped': skipped, 'progress': 0, 'progress_total': 0, 'error': None,
        })

        if not offers:
            _save_task(user_id, {
                'status': 'done', 'scored': 0, 'total': 0,
                'skipped': skipped, 'progress': 0, 'progress_total': 0, 'error': None,
            })
            return

        if method == 'claude':
            from app.services.cv_matcher_claude import ClaudeCVMatcher
            matcher = ClaudeCVMatcher(cv_text)

            def _progress_cb(batches_done, total_batches, offers_done):
                _save_task(user_id, {
                    'status': 'running', 'scored': offers_done, 'total': total,
                    'skipped': skipped, 'progress': batches_done,
                    'progress_total': total_batches, 'error': None,
                })

            scores = matcher.score_offers(offers, progress_callback=_progress_cb)
        else:
            from app.services.cv_matcher import CVMatcher
            matcher = CVMatcher(cv_text)
            scores = matcher.score_offers(offers)

        _persist_scores(db, user_id, offers, scores)
        db.commit()
        _save_task(user_id, {
            'status': 'done', 'scored': len(scores), 'total': total,
            'skipped': skipped, 'progress': 0, 'progress_total': 0, 'error': None,
        })

    except Exception as e:
        logger.error(f"[cv_matching_worker] Error: {e}", exc_info=True)
        db.rollback()
        _save_task(user_id, {
            'status': 'error', 'scored': 0, 'total': 0, 'skipped': 0,
            'progress': 0, 'progress_total': 0, 'error': 'Erreur interne du serveur',
        })
    finally:
        db.close()


def _run_cv_matching(method='tfidf', force=False, domain_id=None, user_id=None):
    """
    Synchronous CV matching — used by cv_upload (tfidf, force=True).
    Returns (scored, skipped).
    """
    if not CV_TEXT_PATH.exists():
        return 0, 0

    cv_text = CV_TEXT_PATH.read_text(encoding="utf-8")
    db = SessionLocal()
    try:
        query, skipped = _build_offer_query(db, domain_id, user_id, force)
        offers = query.all()
        if not offers:
            return 0, skipped

        if method == 'claude':
            from app.services.cv_matcher_claude import ClaudeCVMatcher
            matcher = ClaudeCVMatcher(cv_text)
        else:
            from app.services.cv_matcher import CVMatcher
            matcher = CVMatcher(cv_text)

        scores = matcher.score_offers(offers)
        _persist_scores(db, user_id, offers, scores)
        db.commit()
        return len(scores), skipped
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@bp.route('/api/cv/upload', methods=['POST'])
@admin_required
def cv_upload():
    """
    Accept a PDF or plain-text CV file, extract text, save to disk,
    then run CV matching against all stored offers.
    Query param: ?method=tfidf (default) or ?method=claude
    """
    if 'cv' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['cv']
    if not file.filename:
        return jsonify({'error': 'Empty filename'}), 400

    # Extension + MIME validation for CV uploads
    _cv_allowed = {'.pdf', '.txt'}
    _cv_mimes = {
        '.pdf': {'application/pdf', 'application/octet-stream'},
        '.txt': {'text/plain', 'application/octet-stream'},
    }
    sanitized_cv_name = secure_filename(file.filename)
    if not sanitized_cv_name:
        return jsonify({'error': 'Nom de fichier invalide'}), 400
    cv_ext = Path(sanitized_cv_name).suffix.lower()
    if cv_ext not in _cv_allowed:
        return jsonify({'error': 'Seuls les fichiers .pdf et .txt sont acceptés pour le CV'}), 400
    cv_ct = (file.content_type or '').split(';')[0].strip().lower()
    if cv_ct and cv_ct not in _cv_mimes[cv_ext] and cv_ct not in _BLOCKED_MIMES:
        return jsonify({'error': f'Type MIME {cv_ct!r} incompatible avec {cv_ext}'}), 400
    if cv_ct in _BLOCKED_MIMES:
        return jsonify({'error': f'Type MIME refusé : {cv_ct}'}), 400
    # Size limit: 5 MB
    file.seek(0, 2)
    if file.tell() > MAX_UPLOAD_SIZE:
        return jsonify({'error': 'Fichier trop volumineux (max 5 Mo)'}), 400
    file.seek(0)

    filename = sanitized_cv_name.lower()
    raw = file.read()

    # Extract text
    if cv_ext == '.pdf':
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            cv_text = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            return jsonify({'error': 'PyPDF2 not installed. pip install PyPDF2'}), 500
        except Exception:
            return jsonify({'error': 'Impossible de lire le fichier PDF'}), 400
    else:
        # Assume plain text (UTF-8)
        try:
            cv_text = raw.decode('utf-8')
        except UnicodeDecodeError:
            cv_text = raw.decode('latin-1', errors='replace')

    if not cv_text.strip():
        return jsonify({'error': 'Could not extract text from CV'}), 400

    # Save to disk
    CV_DIR.mkdir(parents=True, exist_ok=True)
    CV_TEXT_PATH.write_text(cv_text, encoding='utf-8')

    method = request.args.get('method', 'tfidf')
    if method not in ('tfidf', 'claude'):
        method = 'tfidf'

    # Run matching — force=True because a new CV invalidates all existing scores
    try:
        scored, skipped = _run_cv_matching(
            method=method,
            force=True,
            domain_id=session.get("domain_id"),
            user_id=session.get("user_id"),
        )
        return jsonify({'ok': True, 'scored': scored, 'method': method})
    except Exception as e:
        return jsonify({'error': 'Erreur interne du serveur'}), 500


@bp.route('/api/cv/rematch', methods=['POST'])
@admin_required
def cv_rematch():
    """
    Launch CV matching asynchronously in a background thread and return immediately.

    Query params:
      method=tfidf|claude  — scoring engine (default: tfidf)
      force=true           — re-score ALL offers, even those already scored

    Returns immediately with {ok, status: 'started'|'already_running', task_id}.
    Poll GET /api/cv/matching-status for progress.
    """
    if not CV_TEXT_PATH.exists():
        return jsonify({'error': 'No CV uploaded yet'}), 404

    method = request.args.get('method', 'tfidf')
    if method not in ('tfidf', 'claude'):
        method = 'tfidf'
    force = request.args.get('force', 'false').lower() == 'true'

    user_id = session.get('user_id')
    domain_id = session.get('domain_id')

    task_id = str(uuid.uuid4())
    initial_state = {
        'status': 'running',
        'task_id': task_id,
        'scored': 0,
        'total': 0,
        'skipped': 0,
        'progress': 0,
        'progress_total': 0,
        'error': None,
    }

    if not _try_start_task(user_id, initial_state):
        existing = _load_task(user_id) or {}
        return jsonify({
            'ok': False,
            'status': 'already_running',
            'scored': existing.get('scored', 0),
            'total': existing.get('total', 0),
        })

    thread = threading.Thread(
        target=_cv_matching_worker,
        args=(user_id, domain_id, method, force),
        daemon=True,
    )
    thread.start()

    return jsonify({'ok': True, 'status': 'started', 'task_id': task_id})


@bp.route('/api/cv/matching-status')
@login_required
def cv_matching_status():
    """Return the current CV matching task state for the logged-in user."""
    user_id = session.get('user_id')
    task = _load_task(user_id)
    if not task:
        return jsonify({'ok': True, 'status': 'none'})
    return jsonify({
        'ok': True,
        'status':          task['status'],
        'scored':          task.get('scored', 0),
        'total':           task.get('total', 0),
        'skipped':         task.get('skipped', 0),
        'progress':        task.get('progress', 0),
        'progress_total':  task.get('progress_total', 0),
        'error':           task.get('error'),
    })


# ── Document management ───────────────────────────────────────────────────────

@bp.route('/documents')
@login_required
def documents():
    """Document library: list uploaded files (CV, cover letters, etc.)."""
    docs_dir = _user_docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(f.name for f in docs_dir.iterdir() if f.is_file())
    return render_template('documents.html', files=files,
                           role=get_current_role(),
                           username=session.get("username"))


@bp.route('/api/documents/upload', methods=['POST'])
@admin_required
def document_upload():
    """Upload a document file (PDF, TXT, DOCX) with strict validation."""
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier fourni'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Nom de fichier vide'}), 400

    # 1. Sanitize filename
    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({'error': 'Nom de fichier invalide après sanitisation'}), 400

    # 2. Extension check — must have exactly one recognised extension
    p = Path(filename)
    ext = p.suffix.lower()
    if not ext:
        return jsonify({'error': 'Le fichier doit avoir une extension (.pdf, .docx, .txt)'}), 400
    if ext not in _ALLOWED_MIMES:
        return jsonify({'error': f'Extension refusée : {ext}. Acceptés : .pdf, .docx, .txt'}), 400

    # 3. Double-extension check (e.g. malware.exe.pdf)
    stem_ext = Path(p.stem).suffix.lower()
    if stem_ext:
        return jsonify({'error': 'Double extension refusée (ex: fichier.exe.pdf)'}), 400

    # 4. MIME type validation
    content_type = (file.content_type or '').split(';')[0].strip().lower()
    if content_type in _BLOCKED_MIMES:
        return jsonify({'error': f'Type MIME refusé : {content_type}'}), 400
    if content_type and content_type not in _ALLOWED_MIMES[ext]:
        return jsonify({'error': f'Type MIME {content_type!r} incompatible avec {ext}'}), 400

    # 5. Size check (read into memory to measure; limit stream)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_UPLOAD_SIZE:
        mb = size / (1024 * 1024)
        return jsonify({'error': f'Fichier trop volumineux ({mb:.1f} Mo). Max : 5 Mo'}), 400

    docs_dir = _user_docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)
    file.save(str(docs_dir / filename))
    return jsonify({'ok': True, 'filename': filename})


@bp.route('/api/documents/<filename>', methods=['GET'])
@login_required
def document_download(filename):
    """Download an uploaded document."""
    filepath = _user_docs_dir() / secure_filename(filename)
    if not filepath.exists():
        return "Fichier introuvable", 404
    return send_file(str(filepath), as_attachment=True,
                     download_name=filepath.name)


@bp.route('/api/documents/<filename>', methods=['DELETE'])
@admin_required
def document_delete(filename):
    """Delete an uploaded document."""
    filepath = _user_docs_dir() / secure_filename(filename)
    if not filepath.exists():
        return jsonify({'error': 'Fichier introuvable'}), 404
    filepath.unlink()
    return jsonify({'ok': True})


# ── Cover letter generation ───────────────────────────────────────────────────

@bp.route('/api/cover-letter/<int:offer_id>', methods=['POST'])
@admin_required
def generate_cover_letter(offer_id):
    """
    Generate a tailored cover letter for an offer using Claude.
    Body JSON: { template_filename: str|"", format: "txt"|"docx" }
    Returns JSON { ok, text, filename } for txt, or binary for docx.
    """
    from config import APIKeys

    db = SessionLocal()
    try:
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            return jsonify({'error': 'Offre introuvable'}), 404

        data = request.get_json() or {}
        template_filename = data.get('template_filename', '').strip()
        output_format = data.get('format', 'txt')
        if output_format not in ('txt', 'docx'):
            output_format = 'txt'

        # Read cover letter template (if provided)
        template_text = ""
        if template_filename:
            tpl_path = _user_docs_dir() / secure_filename(template_filename)
            if tpl_path.exists():
                ext = tpl_path.suffix.lower()
                if ext == '.pdf':
                    try:
                        import PyPDF2
                        reader = PyPDF2.PdfReader(str(tpl_path))
                        template_text = "\n".join(
                            p.extract_text() or "" for p in reader.pages
                        )
                    except Exception:
                        pass
                else:
                    try:
                        template_text = tpl_path.read_text(encoding='utf-8')
                    except UnicodeDecodeError:
                        template_text = tpl_path.read_text(
                            encoding='latin-1', errors='replace'
                        )

        # Build prompt
        if template_text.strip():
            intro = (
                "Adapte cette lettre de motivation existante à la nouvelle offre :\n\n"
                "---\n" + template_text.strip() + "\n---\n\n"
            )
        else:
            intro = "Rédige une lettre de motivation professionnelle.\n\n"

        prompt = (
            intro
            + "Offre ciblée :\n"
            + f"- Poste : {offer.title}\n"
            + f"- Entreprise : {offer.company}\n"
            + f"- Description : {(offer.description or '')[:2000]}\n\n"
            + "Instructions :\n"
            + "- Personnalise l'introduction en mentionnant l'entreprise et le poste\n"
            + "- Mets en avant les compétences les plus pertinentes pour ce rôle\n"
            + "- Ton professionnel et enthousiaste, 3 à 4 paragraphes\n"
            + "- Réponds UNIQUEMENT avec la lettre, sans titre ni commentaires"
        )

        if not APIKeys.ANTHROPIC_API_KEY:
            return jsonify({'error': 'ANTHROPIC_API_KEY non configurée dans .env'}), 503

        from anthropic import Anthropic
        client = Anthropic(api_key=APIKeys.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=APIKeys.ANTHROPIC_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        letter_text = message.content[0].text

        # Sanitize company name for filename
        company_safe = "".join(
            c if c.isalnum() or c in " _-" else "_"
            for c in offer.company
        ).strip().replace(" ", "_")

        # Return binary .docx if python-docx is available
        if output_format == 'docx':
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument()
                for para in letter_text.split('\n\n'):
                    if para.strip():
                        doc.add_paragraph(para.strip())
                buf = io.BytesIO()
                doc.save(buf)
                buf.seek(0)
                dl_name = f"lettre_{company_safe}.docx"
                mime = (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                )
                return send_file(buf, as_attachment=True,
                                 download_name=dl_name, mimetype=mime)
            except ImportError:
                pass  # fall through to txt

        filename = f"lettre_{company_safe}.txt"
        return jsonify({'ok': True, 'text': letter_text, 'filename': filename})

    except Exception as e:
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        db.close()


# ── Admin panel ───────────────────────────────────────────────────────────────

@bp.route('/admin')
@superadmin_required
def admin_page():
    """Admin panel: list all registered users with management actions."""
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.created_at.desc()).all()
        domains = {d.id: d.name for d in db.query(Domain).all()}
        # Count documents per user
        doc_counts: dict[int, int] = {}
        for u in users:
            d = _admin_user_docs_dir(u.id)
            doc_counts[u.id] = sum(1 for f in d.iterdir() if f.is_file()) if d.exists() else 0
        return render_template(
            'admin.html',
            users=users,
            domains=domains,
            doc_counts=doc_counts,
            role=get_current_role(),
            username=session.get("username"),
        )
    finally:
        db.close()


@bp.route('/api/admin/users/<int:user_id>/toggle', methods=['POST'])
@superadmin_required
def admin_toggle_user(user_id):
    """Enable or disable a user account."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        if user.username == session.get("username"):
            return jsonify({'error': 'Impossible de désactiver votre propre compte'}), 400
        user.is_active = not user.is_active
        db.commit()
        return jsonify({'ok': True, 'is_active': user.is_active})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        db.close()


# ── Admin: per-user document management ───────────────────────────────────────

def _admin_user_docs_dir(user_id: int) -> Path:
    """Return the document directory for a given user (admin access)."""
    return DATA_DIR / "documents" / str(user_id)


@bp.route('/admin/documents/<int:user_id>')
@superadmin_required
def admin_user_documents(user_id):
    """Admin view: list and manage documents belonging to a specific user."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return "Utilisateur introuvable", 404
        docs_dir = _admin_user_docs_dir(user_id)
        files = sorted(f.name for f in docs_dir.iterdir() if f.is_file()) if docs_dir.exists() else []
        return render_template(
            'admin_user_docs.html',
            target_user=user,
            files=files,
            role=get_current_role(),
            username=session.get("username"),
        )
    finally:
        db.close()


@bp.route('/api/admin/documents/<int:user_id>/<filename>', methods=['GET'])
@superadmin_required
def admin_document_download(user_id, filename):
    """Admin download of a specific user's document."""
    filepath = _admin_user_docs_dir(user_id) / secure_filename(filename)
    if not filepath.exists():
        return "Fichier introuvable", 404
    return send_file(str(filepath), as_attachment=True, download_name=filepath.name)


@bp.route('/api/admin/documents/<int:user_id>/<filename>', methods=['DELETE'])
@superadmin_required
def admin_document_delete(user_id, filename):
    """Admin delete of a specific user's document."""
    filepath = _admin_user_docs_dir(user_id) / secure_filename(filename)
    if not filepath.exists():
        return jsonify({'error': 'Fichier introuvable'}), 404
    filepath.unlink()
    return jsonify({'ok': True})

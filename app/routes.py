"""
Flask routes for JobHunter dashboard.
Handles all web interface endpoints and API endpoints for AJAX updates.
"""

import io
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import Offer, Tracking
from app.services.filter_engine import normalize_text
from config import TARGET_COMPANIES, DATA_DIR

# Create Blueprint
bp = Blueprint('main', __name__)

VALID_STATUSES = [
    'New', 'Applied', 'Followed up', 'Interview',
    'Accepted', 'Rejected', 'No response',
]

# CV storage paths
CV_DIR = DATA_DIR / "cv"
CV_TEXT_PATH = CV_DIR / "cv_text.txt"


@bp.route('/')
@bp.route('/dashboard')
def dashboard():
    """
    Main dashboard view.
    Displays all job offers with their tracking status in an interactive table.
    """
    db = SessionLocal()
    try:
        offers = db.query(Offer).options(joinedload(Offer.tracking)).all()

        total_offers = len(offers)
        cv_sent_count = db.query(Tracking).filter(Tracking.cv_sent == True).count()
        follow_up_count = db.query(Tracking).filter(Tracking.follow_up_done == True).count()
        interview_count = db.query(Tracking).filter(Tracking.status == 'Interview').count()

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

        return render_template(
            'dashboard.html',
            offers=offers,
            stats=stats,
            sources=sources,
            statuses=VALID_STATUSES,
            target_ids=target_ids,
            has_cv=has_cv,
        )
    finally:
        db.close()


@bp.route('/api/tracking/<int:offer_id>', methods=['PUT'])
def update_tracking(offer_id):
    """
    AJAX endpoint to update tracking data for an offer.
    Accepts JSON with any combination of: status, cv_sent, follow_up_done,
    date_sent, follow_up_date, notes.
    """
    t_start = time.perf_counter()
    db = SessionLocal()
    try:
        t_q0 = time.perf_counter()
        tracking = db.query(Tracking).filter(Tracking.offer_id == offer_id).first()
        t_q1 = time.perf_counter()
        print(f"[DIAG] query tracking: {(t_q1 - t_q0) * 1000:.1f}ms")

        if not tracking:
            offer_exists = db.query(Offer.id).filter(Offer.id == offer_id).scalar()
            if not offer_exists:
                return jsonify({'error': 'Offer not found'}), 404
            tracking = Tracking(offer_id=offer_id, status='New')
            db.add(tracking)

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

    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@bp.route('/offer/<int:offer_id>')
def offer_detail(offer_id):
    """Detailed view of a single job offer."""
    db = SessionLocal()
    try:
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            return "Offer not found", 404
        return render_template('offer_detail.html', offer=offer)
    finally:
        db.close()


@bp.route('/stats')
def stats():
    """Statistics page with detailed metrics."""
    db = SessionLocal()
    try:
        total_offers = db.query(Offer).count()
        tracked_offers = db.query(Tracking).count()
        cv_sent = db.query(Tracking).filter(Tracking.cv_sent == True).count()
        follow_ups = db.query(Tracking).filter(Tracking.follow_up_done == True).count()

        status_counts = {}
        for status in VALID_STATUSES:
            count = db.query(Tracking).filter(Tracking.status == status).count()
            status_counts[status] = count

        stats_data = {
            'total_offers': total_offers,
            'tracked': tracked_offers,
            'cv_sent': cv_sent,
            'follow_ups': follow_ups,
            'status_counts': status_counts,
        }

        # ── Chart data ────────────────────────────────────────────────
        # Offers per source
        source_rows = (
            db.query(Offer.source, func.count(Offer.id))
            .group_by(Offer.source)
            .order_by(func.count(Offer.id).desc())
            .all()
        )
        source_counts = {s: c for s, c in source_rows if s}

        # Top 10 companies by offer count
        company_rows = (
            db.query(Offer.company, func.count(Offer.id))
            .group_by(Offer.company)
            .order_by(func.count(Offer.id).desc())
            .limit(10)
            .all()
        )
        top_companies = {c: n for c, n in company_rows if c}

        # Score distribution in 10 equal buckets (0–10, 10–20, …, 90–100)
        score_rows = db.query(Offer.relevance_score).all()
        score_buckets = [0] * 10
        for (score,) in score_rows:
            s = float(score or 0)
            bucket = min(int(s // 10), 9)
            score_buckets[bucket] += 1

        # CV match score distribution (only when a CV has been uploaded)
        has_cv = CV_TEXT_PATH.exists()
        cv_score_buckets = [0] * 10
        if has_cv:
            cv_rows = db.query(Offer.cv_match_score).filter(
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
        )
    finally:
        db.close()


def _run_cv_matching(method='tfidf'):
    """
    Run CV matching between the stored CV and all offers,
    then persist cv_match_score on each Offer row.

    Args:
        method: 'tfidf' (default, fast) or 'claude' (AI-powered, slower)

    Returns the number of offers scored.
    """
    if not CV_TEXT_PATH.exists():
        return 0

    cv_text = CV_TEXT_PATH.read_text(encoding="utf-8")
    db = SessionLocal()
    try:
        offers = db.query(Offer).all()
        if not offers:
            return 0

        if method == 'claude':
            from app.services.cv_matcher_claude import ClaudeCVMatcher
            matcher = ClaudeCVMatcher(cv_text)
        else:
            from app.services.cv_matcher import CVMatcher
            matcher = CVMatcher(cv_text)

        scores = matcher.score_offers(offers)

        for offer in offers:
            offer.cv_match_score = scores.get(offer.id)

        db.commit()
        return len(scores)
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


@bp.route('/api/cv/upload', methods=['POST'])
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

    filename = file.filename.lower()
    raw = file.read()

    # Extract text
    if filename.endswith('.pdf'):
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(raw))
            cv_text = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            return jsonify({'error': 'PyPDF2 not installed. pip install PyPDF2'}), 500
        except Exception as e:
            return jsonify({'error': f'PDF parse error: {e}'}), 400
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

    # Run matching
    try:
        scored = _run_cv_matching(method=method)
        return jsonify({'ok': True, 'scored': scored, 'method': method})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/cv/rematch', methods=['POST'])
def cv_rematch():
    """
    Re-run CV matching using the already-stored CV text.
    Query param: ?method=tfidf (default) or ?method=claude
    """
    if not CV_TEXT_PATH.exists():
        return jsonify({'error': 'No CV uploaded yet'}), 404

    method = request.args.get('method', 'tfidf')
    if method not in ('tfidf', 'claude'):
        method = 'tfidf'

    try:
        scored = _run_cv_matching(method=method)
        return jsonify({'ok': True, 'scored': scored, 'method': method})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

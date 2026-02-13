"""
Flask routes for JobHunter dashboard.
Handles all web interface endpoints and API endpoints for AJAX updates.
"""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import func

from app.database import SessionLocal
from app.models import Offer, Tracking

# Create Blueprint
bp = Blueprint('main', __name__)

VALID_STATUSES = [
    'New', 'Applied', 'Followed up', 'Interview',
    'Accepted', 'Rejected', 'No response',
]


@bp.route('/')
@bp.route('/dashboard')
def dashboard():
    """
    Main dashboard view.
    Displays all job offers with their tracking status in an interactive table.
    """
    db = SessionLocal()
    try:
        offers = db.query(Offer).outerjoin(Tracking).all()

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

        # Collect unique sources and companies for filter dropdowns
        sources = sorted(set(o.source for o in offers))
        companies = sorted(set(o.company for o in offers))

        return render_template(
            'dashboard.html',
            offers=offers,
            stats=stats,
            sources=sources,
            companies=companies,
            statuses=VALID_STATUSES,
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
    db = SessionLocal()
    try:
        offer = db.query(Offer).filter(Offer.id == offer_id).first()
        if not offer:
            return jsonify({'error': 'Offer not found'}), 404

        tracking = db.query(Tracking).filter(Tracking.offer_id == offer_id).first()
        if not tracking:
            tracking = Tracking(offer_id=offer_id, status='New')
            db.add(tracking)

        data = request.get_json()

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
        db.commit()

        return jsonify({
            'ok': True,
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

        return render_template('stats.html', stats=stats_data)
    finally:
        db.close()

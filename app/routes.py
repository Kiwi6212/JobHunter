"""
Flask routes for JobHunter dashboard.
Handles all web interface endpoints.
"""

from flask import Blueprint, render_template
from app.database import SessionLocal
from app.models import Offer, Tracking

# Create Blueprint
bp = Blueprint('main', __name__)


@bp.route('/')
@bp.route('/dashboard')
def dashboard():
    """
    Main dashboard view.
    Displays all job offers with their tracking status in a table.
    """
    db = SessionLocal()
    try:
        # Fetch all offers with their tracking data
        offers = db.query(Offer).outerjoin(Tracking).all()

        # Statistics
        total_offers = len(offers)
        offers_with_tracking = db.query(Tracking).count()
        cv_sent_count = db.query(Tracking).filter(Tracking.cv_sent == True).count()

        stats = {
            'total_offers': total_offers,
            'tracked': offers_with_tracking,
            'cv_sent': cv_sent_count,
        }

        return render_template('dashboard.html', offers=offers, stats=stats)
    finally:
        db.close()


@bp.route('/offer/<int:offer_id>')
def offer_detail(offer_id):
    """
    Detailed view of a single job offer.

    Args:
        offer_id: ID of the offer to display
    """
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
    """
    Statistics page with detailed metrics.
    """
    db = SessionLocal()
    try:
        # Gather statistics
        total_offers = db.query(Offer).count()
        tracked_offers = db.query(Tracking).count()
        cv_sent = db.query(Tracking).filter(Tracking.cv_sent == True).count()
        follow_ups = db.query(Tracking).filter(Tracking.follow_up_done == True).count()

        # Status breakdown
        status_counts = {}
        for status in ['New', 'Applied', 'Followed up', 'Interview', 'Accepted', 'Rejected', 'No response']:
            count = db.query(Tracking).filter(Tracking.status == status).count()
            status_counts[status] = count

        stats_data = {
            'total_offers': total_offers,
            'tracked': tracked_offers,
            'cv_sent': cv_sent,
            'follow_ups': follow_ups,
            'status_counts': status_counts
        }

        return render_template('stats.html', stats=stats_data)
    finally:
        db.close()

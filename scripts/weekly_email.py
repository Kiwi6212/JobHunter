"""
Weekly email notifications for JobHunter.
Sends a digest of the best new job offers (Match IA > 50%) from the last 7 days
to each eligible user (active, confirmed email, subscribed, has CV text).

Eligible users receive the top 10 offers sorted by cv_match_score descending.

Usage:
    python scripts/weekly_email.py

Recommended cron (every Monday at 09:00 UTC):
    0 9 * * 1 cd /home/ubuntu/JobHunter && /home/ubuntu/JobHunter/venv/bin/python scripts/weekly_email.py >> /home/ubuntu/logs/weekly_email.log 2>&1
"""

import hashlib
import hmac
import html as _html
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Add project root to Python path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import and_

from app.database import SessionLocal, init_db
from app.models import User, Offer, UserOffer
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("weekly_email")

MIN_MATCH_SCORE = 50
MAX_OFFERS = 10
LOOKBACK_DAYS = 7
BASE_URL = Config.BASE_URL if hasattr(Config, "BASE_URL") else "https://myjobhunter.fr"


def _unsubscribe_token(user_id: int) -> str:
    """Generate an HMAC-based unsubscribe token for a user."""
    secret = Config.SECRET_KEY or "fallback-secret"
    msg = f"unsubscribe-weekly:{user_id}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _build_email_html(username: str, offers: list, unsubscribe_url: str) -> str:
    """Build the weekly digest HTML email matching the existing email style."""
    safe_username = _html.escape(username)
    safe_unsub = _html.escape(unsubscribe_url)

    # Build offer rows
    offer_rows = ""
    for offer in offers:
        safe_title = _html.escape(offer.title or "Sans titre")
        safe_company = _html.escape(offer.company or "Entreprise inconnue")
        safe_location = _html.escape(offer.location or "France")
        score = offer._match_score  # attached by the query
        detail_url = _html.escape(f"{BASE_URL}/offer/{offer.id}")
        offer_rows += f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;">
                <a href="{detail_url}" style="color:#2563eb;text-decoration:none;font-weight:600;font-size:.92rem;">
                  {safe_title}
                </a>
                <div style="color:#64748b;font-size:.82rem;margin-top:2px;">
                  {safe_company} &middot; {safe_location}
                </div>
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:center;white-space:nowrap;">
                <span style="display:inline-block;background:{'#dcfce7' if score >= 70 else '#fef9c3'};
                             color:{'#15803d' if score >= 70 else '#854d0e'};
                             padding:3px 10px;border-radius:12px;font-size:.82rem;font-weight:600;">
                  {score:.0f}%
                </span>
              </td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;padding:40px 0;">
    <tr><td align="center">
      <table width="580" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);overflow:hidden;">
        <tr>
          <td style="background:linear-gradient(135deg,#2563eb,#1d4ed8);padding:28px 40px;text-align:center;">
            <span style="font-size:2.2rem;">&#127919;</span>
            <h1 style="margin:8px 0 0;color:#ffffff;font-size:1.4rem;font-weight:700;letter-spacing:-.3px;">
              MyJobHunter
            </h1>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <h2 style="margin:0 0 12px;font-size:1.15rem;color:#0f172a;">
              Vos meilleures offres de la semaine
            </h2>
            <p style="margin:0 0 20px;color:#475569;font-size:.95rem;line-height:1.6;">
              Bonjour <strong>{safe_username}</strong>,<br>
              Voici les <strong>{len(offers)}</strong> offres les plus pertinentes
              d\u00e9couvertes cette semaine pour votre profil.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;margin-bottom:24px;">
              <tr style="background:#f1f5f9;">
                <th style="padding:10px 12px;text-align:left;font-size:.82rem;color:#475569;font-weight:600;
                           border-bottom:1px solid #e2e8f0;">
                  Offre
                </th>
                <th style="padding:10px 12px;text-align:center;font-size:.82rem;color:#475569;font-weight:600;
                           border-bottom:1px solid #e2e8f0;width:80px;">
                  Match
                </th>
              </tr>
              {offer_rows}
            </table>
            <table cellpadding="0" cellspacing="0" width="100%" style="margin-bottom:24px;">
              <tr>
                <td align="center">
                  <a href="{_html.escape(BASE_URL)}/dashboard"
                     style="display:inline-block;background:#2563eb;color:#ffffff;
                            text-decoration:none;padding:14px 36px;border-radius:8px;
                            font-size:1rem;font-weight:600;letter-spacing:-.2px;">
                    Voir le dashboard &#8594;
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0;color:#94a3b8;font-size:.82rem;line-height:1.5;">
              Vous recevez cet email car vous \u00eates inscrit aux notifications hebdomadaires
              sur MyJobHunter.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#f8fafc;padding:20px 40px;text-align:center;
                     border-top:1px solid #e2e8f0;">
            <p style="margin:0 0 6px;color:#94a3b8;font-size:.78rem;">
              &copy; 2026 MyJobHunter &middot; Cet email est automatique, ne pas r\u00e9pondre.
            </p>
            <p style="margin:0;">
              <a href="{safe_unsub}" style="color:#94a3b8;font-size:.78rem;text-decoration:underline;">
                Se d\u00e9sabonner des emails hebdomadaires
              </a>
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def send_weekly_emails():
    """Main entry point: find eligible users and send weekly digests."""
    init_db()

    # Import Flask app + mail inside function to have app context
    from app import create_app, mail
    from flask_mail import Message

    app = create_app()

    db = SessionLocal()
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    cutoff_naive = cutoff.replace(tzinfo=None)

    try:
        # Eligible users: active, email confirmed, has email, subscribed to weekly
        users = db.query(User).filter(
            User.is_active.is_(True),
            User.email.isnot(None),
            User.email != "",
            User.email_confirmed.is_(True),
            User.email_weekly.is_(True),
        ).all()

        if not users:
            log.info("No eligible users for weekly email. Done.")
            return

        log.info("Found %d eligible user(s) for weekly digest.", len(users))
        sent = 0
        skipped = 0

        for user in users:
            # Find offers from last 7 days with cv_match_score > MIN_MATCH_SCORE
            # for this user's domain
            query = db.query(Offer, UserOffer.cv_match_score).outerjoin(
                UserOffer,
                and_(
                    UserOffer.offer_id == Offer.id,
                    UserOffer.user_id == user.id,
                ),
            ).filter(
                Offer.is_active.is_(True),
                Offer.found_date >= cutoff_naive,
            )

            # Scope to user's domain if set
            if user.domain_id:
                query = query.filter(Offer.domain_id == user.domain_id)

            # Filter by match score (from UserOffer if exists, else Offer.cv_match_score)
            from sqlalchemy import func, case
            match_score = func.coalesce(UserOffer.cv_match_score, Offer.cv_match_score)
            query = query.filter(match_score >= MIN_MATCH_SCORE)
            query = query.order_by(match_score.desc()).limit(MAX_OFFERS)

            results = query.all()

            if not results:
                log.info("User %s (id=%d): no matching offers, skipping.", user.username, user.id)
                skipped += 1
                continue

            # Attach match score to offer objects for template
            offers = []
            for offer, score in results:
                offer._match_score = score or 0
                offers.append(offer)

            # Build unsubscribe URL
            token = _unsubscribe_token(user.id)
            unsub_url = f"{BASE_URL}/api/account/unsubscribe-weekly?user_id={user.id}&token={token}"

            html_body = _build_email_html(user.username, offers, unsub_url)

            with app.app_context():
                try:
                    msg = Message(
                        subject=f"MyJobHunter - {len(offers)} offres cette semaine",
                        recipients=[user.email],
                        html=html_body,
                    )
                    mail.send(msg)
                    sent += 1
                    log.info("Sent weekly digest to %s (%s): %d offers.", user.username, user.email, len(offers))
                except Exception as exc:
                    log.error("Failed to send email to %s (%s): %s", user.username, user.email, exc)

        log.info("Weekly digest complete: %d sent, %d skipped (no offers).", sent, skipped)

    except Exception:
        log.exception("Error during weekly email — aborted.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    send_weekly_emails()

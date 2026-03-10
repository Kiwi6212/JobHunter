"""
Initialize the SaaS database for JobHunter.

Actions performed:
  1. Create default domains (5 job-search specialties)
  2. Create the admin user in the DB from .env credentials (bcrypt-hashed)
  3. Migrate existing Tracking rows to UserOffer for the admin user
  4. Assign existing offers to domain 1 (Sysadmin) if not yet assigned

Usage:
    python scripts/init_saas.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app import create_app, bcrypt
from app.database import SessionLocal, init_db
from app.models import Domain, User, UserOffer, Offer, Tracking
from config import Config

DOMAINS = [
    {
        "name": "Sysadmin / Infrastructure",
        "description": "Administrateur systèmes et réseaux, Cloud",
    },
    {
        "name": "Développement",
        "description": "Développeur logiciel, web, mobile",
    },
    {
        "name": "Data / IA",
        "description": "Data scientist, ingénieur ML, analyste données",
    },
    {
        "name": "Cybersécurité",
        "description": "Analyste sécurité, pentesteur, SOC",
    },
    {
        "name": "Cloud / DevOps",
        "description": "Ingénieur cloud, SRE, DevOps",
    },
    {
        "name": "Droit",
        "description": "Juriste, avocat, compliance, contentieux, notariat",
    },
    {
        "name": "Commerce / Marketing",
        "description": "Commercial, marketing, business developer, e-commerce",
    },
    {
        "name": "Santé",
        "description": "Infirmier, aide-soignant, pharmacie, paramédical",
    },
    {
        "name": "Ingénierie",
        "description": "Ingénieur mécanique, électronique, production, qualité",
    },
]


def main():
    app = create_app()
    with app.app_context():
        print("=" * 55)
        print("JobHunter — SaaS Initialization")
        print("=" * 55)

        # Ensure all tables exist (including new ones)
        init_db()
        print()

        db = SessionLocal()
        try:
            # ── 1. Domains ────────────────────────────────────────
            print("[1/4] Creating domains...")
            for d in DOMAINS:
                existing = db.query(Domain).filter(Domain.name == d["name"]).first()
                if not existing:
                    db.add(Domain(name=d["name"], description=d["description"]))
                    print(f"      [+] {d['name']}")
                else:
                    print(f"      [=] {d['name']} (already exists)")
            db.commit()

            # ── 2. Admin user ─────────────────────────────────────
            print("\n[2/4] Creating admin user in DB...")
            admin_data = None
            for uname, udata in Config.USERS.items():
                if udata.get("role") == "admin":
                    admin_data = {"username": uname, "password": udata["password"]}
                    break

            if not admin_data:
                print("      [!] No admin user found in Config.USERS — skipping.")
                return

            admin_user = db.query(User).filter(
                User.username == admin_data["username"]
            ).first()

            if not admin_user:
                pw_hash = bcrypt.generate_password_hash(
                    admin_data["password"]
                ).decode("utf-8")
                admin_user = User(
                    username=admin_data["username"],
                    password_hash=pw_hash,
                    role="admin",
                    domain_id=None,  # Admin sees all domains
                )
                db.add(admin_user)
                db.commit()
                print(f"      [+] Admin '{admin_data['username']}' created.")
            else:
                print(f"      [=] Admin '{admin_data['username']}' already in DB.")

            # ── 3. Migrate Tracking → UserOffer ───────────────────
            print("\n[3/4] Migrating Tracking records to UserOffer...")
            tracking_rows = db.query(Tracking).all()
            migrated = 0
            for t in tracking_rows:
                exists = db.query(UserOffer).filter(
                    UserOffer.user_id == admin_user.id,
                    UserOffer.offer_id == t.offer_id,
                ).first()
                if not exists:
                    db.add(UserOffer(
                        user_id=admin_user.id,
                        offer_id=t.offer_id,
                        status=t.status,
                        cv_sent=t.cv_sent,
                        follow_up_done=t.follow_up_done,
                        date_sent=t.date_sent,
                        follow_up_date=t.follow_up_date,
                        notes=t.notes,
                    ))
                    migrated += 1
            if migrated:
                db.commit()
                print(f"      [+] Migrated {migrated} rows.")
            else:
                print("      [=] Nothing to migrate.")

            # ── 4. Assign existing offers to domain 1 ─────────────
            print("\n[4/4] Assigning untagged offers to 'Sysadmin / Infrastructure'...")
            domain1 = db.query(Domain).filter(
                Domain.name == "Sysadmin / Infrastructure"
            ).first()
            if domain1:
                untagged = db.query(Offer).filter(Offer.domain_id == None).count()  # noqa: E711
                if untagged:
                    db.query(Offer).filter(Offer.domain_id == None).update(  # noqa: E711
                        {Offer.domain_id: domain1.id}
                    )
                    db.commit()
                    print(f"      [+] Tagged {untagged} offers with domain_id={domain1.id}.")
                else:
                    print("      [=] All offers already tagged.")

            print("\n[OK] SaaS initialization complete!")
            print("     You can now log in and register new users at /register")

        finally:
            db.close()


if __name__ == "__main__":
    main()

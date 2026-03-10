"""
Add new domains to the JobHunter database.

Inserts Droit, Commerce / Marketing, Santé, and Ingénierie domains
if they don't already exist.

Usage:
    python scripts/add_domains.py
"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app import create_app
from app.database import SessionLocal, init_db
from app.models import Domain

NEW_DOMAINS = [
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
        init_db()
        db = SessionLocal()
        try:
            added = 0
            for d in NEW_DOMAINS:
                existing = db.query(Domain).filter(Domain.name == d["name"]).first()
                if not existing:
                    db.add(Domain(name=d["name"], description=d["description"]))
                    print(f"  [+] {d['name']} — {d['description']}")
                    added += 1
                else:
                    print(f"  [=] {d['name']} (already exists)")
            db.commit()
            print(f"\n[OK] {added} domain(s) added.")
        finally:
            db.close()


if __name__ == "__main__":
    main()

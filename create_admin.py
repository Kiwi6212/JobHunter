#!/usr/bin/env python3
"""Quick script to create an admin user for local development."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.models import User, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
import bcrypt

DATABASE_URL = "sqlite:///data/jobhunter.db"
engine = create_engine(DATABASE_URL)

username = "admin"
password = "admin123"
email = "admin@localhost"

password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

with Session(engine) as session:
    existing = session.query(User).filter(User.username == username).first()
    if existing:
        print(f"[OK] Admin user '{username}' already exists.")
    else:
        user = User(
            username=username,
            password_hash=password_hash,
            role="admin",
            is_active=True,
            email=email,
        )
        session.add(user)
        session.commit()
        print(f"[OK] Admin user created: {username} / {password}")

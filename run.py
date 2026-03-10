"""
Entry point to run the JobHunter Flask application.

Usage:
    python run.py
"""

from app import create_app

app = create_app()

if __name__ == '__main__':
    host = '0.0.0.0' if not app.config.get('DEBUG', False) else '127.0.0.1'
    app.run(host=host, port=5000, debug=app.config.get('DEBUG', False))

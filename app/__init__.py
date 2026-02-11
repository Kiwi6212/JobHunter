"""
Flask application factory for JobHunter.
Initializes the Flask app with configuration and registers blueprints.
"""

from flask import Flask
from flask_cors import CORS
from config import Config


def create_app(config_class=Config):
    """
    Create and configure the Flask application.

    Args:
        config_class: Configuration class to use (default: Config)

    Returns:
        Flask application instance
    """
    # Initialize Flask app
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Enable CORS
    CORS(app)

    # Import and register routes
    from app import routes
    app.register_blueprint(routes.bp)

    return app
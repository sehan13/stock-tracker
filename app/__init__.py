"""
Stock Tracker - a small inventory management web app.

This file uses the "application factory" pattern: create_app() builds and
configures the Flask app. Tests call it with a temporary database so they
never touch real data.
"""
import os
from flask import Flask

from . import db
from .routes import bp


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    # Default settings. The database file lives in the "instance" folder.
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.instance_path, "stock.sqlite"),
        LOW_STOCK_DEFAULT=10,
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)          # register database helpers + CLI commands
    app.register_blueprint(bp)  # register all the pages (routes)

    # Make sure the tables exist the first time the app runs.
    with app.app_context():
        db.init_db_if_missing()

    # Template helper: format a number as pounds, e.g. 1234.5 -> £1,234.50
    @app.template_filter("gbp")
    def gbp(value):
        return f"£{value:,.2f}"

    return app

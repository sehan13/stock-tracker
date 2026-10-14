"""
Database helpers.

We use Python's built-in sqlite3 module and write plain SQL, so every query
in this project is visible and easy to explain.
"""
import sqlite3

import click
from flask import current_app, g


def get_db():
    """Return one database connection per request (stored on Flask's `g`)."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row          # rows behave like dictionaries
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """(Re)create all tables from schema.sql. Deletes existing data!"""
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        db.executescript(f.read().decode("utf-8"))


def init_db_if_missing():
    db = get_db()
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='products'"
    ).fetchone()
    if not exists:
        init_db()
    close_db()


@click.command("init-db")
def init_db_command():
    """flask --app app init-db  -> wipe and recreate the database."""
    init_db()
    click.echo("Database initialised.")


@click.command("seed")
@click.argument("csv_path", default="sample_data/products.csv")
def seed_command(csv_path):
    """flask --app app seed  -> load sample products from a CSV file."""
    from .services import import_products_csv

    with open(csv_path, newline="", encoding="utf-8") as f:
        result = import_products_csv(f)
    click.echo(f"Added {result['added']}, updated {result['updated']}, "
               f"{len(result['errors'])} errors.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(seed_command)

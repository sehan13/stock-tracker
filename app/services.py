"""
Business logic: validation, stock movements, CSV import/export and reporting.

Keeping this separate from routes.py means the rules can be unit-tested
without going through web pages.
"""
import csv
import io

from .db import get_db

REQUIRED_COLUMNS = {"sku", "name", "category", "quantity", "reorder_level", "unit_price"}


class StockError(ValueError):
    """Raised when a request would break a stock rule."""


# ---------------------------------------------------------------- validation
def validate_product(data):
    """Check and clean product form/CSV data. Returns (clean_dict, errors)."""
    errors = []
    clean = {
        "sku": (data.get("sku") or "").strip().upper(),
        "name": (data.get("name") or "").strip(),
        "category": (data.get("category") or "").strip().title(),
    }
    for field in ("sku", "name", "category"):
        if not clean[field]:
            errors.append(f"{field.replace('_', ' ').title()} is required.")

    for field, cast in (("quantity", int), ("reorder_level", int), ("unit_price", float)):
        raw = str(data.get(field, "")).strip()
        try:
            value = cast(raw)
            if value < 0:
                raise ValueError
            clean[field] = round(value, 2) if cast is float else value
        except ValueError:
            label = field.replace("_", " ")
            kind = "a whole number" if cast is int else "a number"
            errors.append(f"{label.capitalize()} must be {kind} of 0 or more.")
    return clean, errors


# ---------------------------------------------------------------- products
def get_products(search="", category="", low_only=False):
    sql = "SELECT * FROM products WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR sku LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        sql += " AND category = ?"
        params.append(category)
    if low_only:
        sql += " AND quantity <= reorder_level"
    sql += " ORDER BY name"
    return get_db().execute(sql, params).fetchall()


def get_product(product_id):
    return get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()


def get_categories():
    rows = get_db().execute("SELECT DISTINCT category FROM products ORDER BY category")
    return [r["category"] for r in rows]


def sku_taken(sku, ignore_id=None):
    row = get_db().execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
    return row is not None and row["id"] != ignore_id


def create_product(p):
    db = get_db()
    cur = db.execute(
        "INSERT INTO products (sku, name, category, quantity, reorder_level, unit_price) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (p["sku"], p["name"], p["category"], p["quantity"], p["reorder_level"], p["unit_price"]),
    )
    if p["quantity"]:
        db.execute("INSERT INTO movements (product_id, change, reason) VALUES (?, ?, ?)",
                   (cur.lastrowid, p["quantity"], "Opening stock"))
    db.commit()
    return cur.lastrowid


def update_product(product_id, p):
    """Update details. Quantity changes go through record_movement so they're audited."""
    db = get_db()
    db.execute(
        "UPDATE products SET sku=?, name=?, category=?, reorder_level=?, unit_price=? WHERE id=?",
        (p["sku"], p["name"], p["category"], p["reorder_level"], p["unit_price"], product_id),
    )
    db.commit()


def delete_product(product_id):
    db = get_db()
    db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    db.commit()


# ---------------------------------------------------------------- stock movements
def record_movement(product_id, change, reason):
    """Add (positive) or remove (negative) stock. Stock can never go below zero."""
    if change == 0:
        raise StockError("Quantity must not be zero.")
    reason = (reason or "").strip()
    if not reason:
        raise StockError("Please give a reason for the stock change.")

    db = get_db()
    product = get_product(product_id)
    if product is None:
        raise StockError("Product not found.")
    new_qty = product["quantity"] + change
    if new_qty < 0:
        raise StockError(f"Not enough stock: only {product['quantity']} available.")

    db.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product_id))
    db.execute("INSERT INTO movements (product_id, change, reason) VALUES (?, ?, ?)",
               (product_id, change, reason))
    db.commit()
    return new_qty


def get_movements(product_id=None, limit=50):
    sql = ("SELECT m.*, p.name, p.sku FROM movements m "
           "JOIN products p ON p.id = m.product_id")
    params = []
    if product_id:
        sql += " WHERE m.product_id = ?"
        params.append(product_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    return get_db().execute(sql, params).fetchall()


# ---------------------------------------------------------------- CSV import / export
def import_products_csv(file_obj):
    """
    Import products from CSV. New SKUs are added; existing SKUs are updated.
    Invalid rows are skipped and reported with their row number, so one bad
    row never blocks the whole file.
    """
    reader = csv.DictReader(file_obj)
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise StockError("CSV is missing required column(s): " + ", ".join(sorted(missing)))

    result = {"added": 0, "updated": 0, "errors": []}
    db = get_db()
    for row_num, row in enumerate(reader, start=2):      # row 1 is the header
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        clean, errors = validate_product(row)
        if errors:
            result["errors"].append(f"Row {row_num}: " + " ".join(errors))
            continue

        existing = db.execute("SELECT * FROM products WHERE sku = ?", (clean["sku"],)).fetchone()
        if existing:
            update_product(existing["id"], clean)
            diff = clean["quantity"] - existing["quantity"]
            if diff:
                record_movement(existing["id"], diff, "CSV import adjustment")
            result["updated"] += 1
        else:
            create_product(clean)
            result["added"] += 1
    return result


def export_products_csv():
    """Return all products (plus stock value and status) as CSV text."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["sku", "name", "category", "quantity", "reorder_level",
                     "unit_price", "stock_value", "status"])
    for p in get_products():
        status = "LOW" if p["quantity"] <= p["reorder_level"] else "OK"
        writer.writerow([p["sku"], p["name"], p["category"], p["quantity"], p["reorder_level"],
                         f"{p['unit_price']:.2f}", f"{p['quantity'] * p['unit_price']:.2f}", status])
    return out.getvalue()


# ---------------------------------------------------------------- dashboard
def dashboard_stats():
    db = get_db()
    totals = db.execute(
        "SELECT COUNT(*) AS products, COALESCE(SUM(quantity), 0) AS units, "
        "COALESCE(SUM(quantity * unit_price), 0) AS value, "
        "COALESCE(SUM(CASE WHEN quantity <= reorder_level THEN 1 ELSE 0 END), 0) AS low "
        "FROM products"
    ).fetchone()
    by_category = db.execute(
        "SELECT category, SUM(quantity) AS units, SUM(quantity * unit_price) AS value "
        "FROM products GROUP BY category ORDER BY value DESC"
    ).fetchall()
    low_stock = db.execute(
        "SELECT * FROM products WHERE quantity <= reorder_level "
        "ORDER BY (quantity * 1.0 / MAX(reorder_level, 1)) LIMIT 10"
    ).fetchall()
    return {
        "totals": totals,
        "by_category": by_category,
        "low_stock": low_stock,
        "recent": get_movements(limit=8),
    }

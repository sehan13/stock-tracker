"""
REST API: the same features as the web pages, returned as JSON.

Endpoints (all under /api):
    GET    /api/products                    list products (?q=, ?category=, ?low=1)
    GET    /api/products/<id>               one product + its recent movements
    POST   /api/products                    create a product (JSON body)
    PATCH  /api/products/<id>               update details (not quantity)
    DELETE /api/products/<id>               delete a product
    POST   /api/products/<id>/movements     record stock in/out {"change": -3, "reason": "..."}
    GET    /api/stats                       dashboard totals

The API reuses services.py, so the web pages and the API always follow the
same business rules.
"""
from flask import Blueprint, jsonify, request

from . import services as s

api = Blueprint("api", __name__, url_prefix="/api")


# ---------------------------------------------------------------- helpers
def product_to_dict(p):
    """Convert a database row into a JSON-friendly dictionary."""
    return {
        "id": p["id"],
        "sku": p["sku"],
        "name": p["name"],
        "category": p["category"],
        "quantity": p["quantity"],
        "reorder_level": p["reorder_level"],
        "unit_price": p["unit_price"],
        "stock_value": round(p["quantity"] * p["unit_price"], 2),
        "low_stock": p["quantity"] <= p["reorder_level"],
    }


def movement_to_dict(m):
    return {"id": m["id"], "change": m["change"], "reason": m["reason"], "created_at": m["created_at"]}


def error(message, status, details=None):
    """Return errors in one consistent JSON shape."""
    body = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


def get_json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- products
@api.get("/products")
def list_products():
    products = s.get_products(
        search=request.args.get("q", "").strip(),
        category=request.args.get("category", ""),
        low_only=request.args.get("low") == "1",
    )
    return jsonify([product_to_dict(p) for p in products])


@api.get("/products/<int:product_id>")
def get_product(product_id):
    p = s.get_product(product_id)
    if p is None:
        return error("Product not found.", 404)
    result = product_to_dict(p)
    result["movements"] = [movement_to_dict(m) for m in s.get_movements(product_id, limit=20)]
    return jsonify(result)


@api.post("/products")
def create_product():
    data = get_json_body()
    if data is None:
        return error("Request body must be a JSON object.", 400)
    data.setdefault("quantity", 0)
    data.setdefault("reorder_level", 10)

    clean, errors = s.validate_product(data)
    if errors:
        return error("Validation failed.", 400, errors)
    if s.sku_taken(clean["sku"]):
        return error(f"SKU {clean['sku']} already exists.", 409)

    new_id = s.create_product(clean)
    return jsonify(product_to_dict(s.get_product(new_id))), 201


@api.patch("/products/<int:product_id>")
def update_product(product_id):
    p = s.get_product(product_id)
    if p is None:
        return error("Product not found.", 404)
    data = get_json_body()
    if data is None:
        return error("Request body must be a JSON object.", 400)
    if "quantity" in data:
        return error("Quantity can't be edited directly. Use POST /api/products/<id>/movements.", 400)

    # Start from the current values and overwrite only the fields sent
    merged = dict(p) | data
    clean, errors = s.validate_product(merged)
    if errors:
        return error("Validation failed.", 400, errors)
    if s.sku_taken(clean["sku"], ignore_id=product_id):
        return error(f"SKU {clean['sku']} already exists.", 409)

    s.update_product(product_id, clean)
    return jsonify(product_to_dict(s.get_product(product_id)))


@api.delete("/products/<int:product_id>")
def delete_product(product_id):
    if s.get_product(product_id) is None:
        return error("Product not found.", 404)
    s.delete_product(product_id)
    return "", 204


# ---------------------------------------------------------------- stock movements
@api.post("/products/<int:product_id>/movements")
def add_movement(product_id):
    if s.get_product(product_id) is None:
        return error("Product not found.", 404)
    data = get_json_body()
    if data is None:
        return error("Request body must be a JSON object.", 400)

    change = data.get("change")
    if not isinstance(change, int) or isinstance(change, bool):
        return error("'change' must be a whole number (positive = in, negative = out).", 400)
    try:
        s.record_movement(product_id, change, data.get("reason"))
    except s.StockError as e:
        return error(str(e), 400)
    return jsonify(product_to_dict(s.get_product(product_id))), 201


# ---------------------------------------------------------------- stats
@api.get("/stats")
def stats():
    data = s.dashboard_stats()
    t = data["totals"]
    return jsonify({
        "products": t["products"],
        "units": t["units"],
        "stock_value": round(t["value"], 2),
        "low_stock_count": t["low"],
        "by_category": [
            {"category": c["category"], "units": c["units"], "value": round(c["value"], 2)}
            for c in data["by_category"]
        ],
    })


# Any unknown /api/... URL returns JSON instead of an HTML page
@api.app_errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith("/api/"):
        return error("Method not allowed.", 405)
    return e

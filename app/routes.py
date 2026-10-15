"""
Routes: each function handles one page or form in the app.
They stay thin and call services.py for the real work.
"""
import io

from flask import (Blueprint, Response, abort, flash, redirect,
                   render_template, request, url_for)

from . import services as s

bp = Blueprint("stock", __name__)


@bp.route("/")
def dashboard():
    return render_template("dashboard.html", stats=s.dashboard_stats())


# ---------------------------------------------------------------- products
@bp.route("/products")
def products():
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "")
    low_only = request.args.get("low") == "1"
    return render_template(
        "products.html",
        products=s.get_products(search, category, low_only),
        categories=s.get_categories(),
        search=search, category=category, low_only=low_only,
    )


@bp.route("/products/new", methods=["GET", "POST"])
def new_product():
    form = request.form if request.method == "POST" else {"reorder_level": 10}
    if request.method == "POST":
        clean, errors = s.validate_product(request.form)
        if not errors and s.sku_taken(clean["sku"]):
            errors.append(f"SKU {clean['sku']} already exists.")
        if not errors:
            s.create_product(clean)
            flash(f"Added {clean['name']}.", "success")
            return redirect(url_for("stock.products"))
        for e in errors:
            flash(e, "error")
    return render_template("product_form.html", form=form, product=None)


@bp.route("/products/<int:product_id>")
def product_detail(product_id):
    product = s.get_product(product_id) or abort(404)
    return render_template("product_detail.html", product=product,
                           movements=s.get_movements(product_id))


@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    product = s.get_product(product_id) or abort(404)
    form = request.form if request.method == "POST" else product
    if request.method == "POST":
        # Quantity is changed via stock movements, so keep the current value here
        data = request.form.to_dict() | {"quantity": product["quantity"]}
        clean, errors = s.validate_product(data)
        if not errors and s.sku_taken(clean["sku"], ignore_id=product_id):
            errors.append(f"SKU {clean['sku']} already exists.")
        if not errors:
            s.update_product(product_id, clean)
            flash("Product updated.", "success")
            return redirect(url_for("stock.product_detail", product_id=product_id))
        for e in errors:
            flash(e, "error")
    return render_template("product_form.html", form=form, product=product)


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    product = s.get_product(product_id) or abort(404)
    s.delete_product(product_id)
    flash(f"Deleted {product['name']}.", "success")
    return redirect(url_for("stock.products"))


@bp.route("/products/<int:product_id>/movement", methods=["POST"])
def add_movement(product_id):
    s.get_product(product_id) or abort(404)
    try:
        qty = int(request.form.get("quantity", 0))
        if qty <= 0:
            raise s.StockError("Quantity must be a whole number above 0.")
        change = qty if request.form.get("direction") == "in" else -qty
        new_qty = s.record_movement(product_id, change, request.form.get("reason"))
        flash(f"Stock updated: now {new_qty} in stock.", "success")
    except ValueError as e:     # StockError is a ValueError too
        msg = str(e) if isinstance(e, s.StockError) else "Quantity must be a whole number."
        flash(msg, "error")
    return redirect(url_for("stock.product_detail", product_id=product_id))


# ---------------------------------------------------------------- CSV
@bp.route("/import", methods=["GET", "POST"])
def import_csv():
    result = None
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename.lower().endswith(".csv"):
            flash("Please choose a .csv file.", "error")
        else:
            try:
                text = io.StringIO(file.stream.read().decode("utf-8-sig"))
                result = s.import_products_csv(text)
                flash(f"Import finished: {result['added']} added, {result['updated']} updated.",
                      "success")
            except UnicodeDecodeError:
                flash("Could not read the file. Please save it as UTF-8 CSV.", "error")
            except s.StockError as e:
                flash(str(e), "error")
    return render_template("import.html", result=result)


@bp.route("/export.csv")
def export_csv():
    return Response(
        s.export_products_csv(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=stock_report.csv"},
    )


@bp.app_errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return {"error": "Not found."}, 404
    return render_template("404.html"), 404

"""
Automated tests for Stock Tracker.

Run with:   python -m unittest discover -s tests -v
(or `pytest` if you have it installed)

Each test gets a brand-new temporary database, so tests never affect each
other or your real data.
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app                       # noqa: E402
from app import services as s                     # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample_data", "products.csv")


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        self.app = create_app({"TESTING": True, "DATABASE": self.db_path, "SECRET_KEY": "test"})
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def add(self, sku="T-1", qty=10, reorder=5, price=2.5, name="Test Tap", category="Taps"):
        return s.create_product({"sku": sku, "name": name, "category": category,
                                 "quantity": qty, "reorder_level": reorder, "unit_price": price})


class ValidationTests(BaseTest):
    def test_valid_product_is_cleaned(self):
        clean, errors = s.validate_product({"sku": " bth-1 ", "name": "Tap", "category": "taps",
                                            "quantity": "5", "reorder_level": "2", "unit_price": "9.999"})
        self.assertEqual(errors, [])
        self.assertEqual(clean["sku"], "BTH-1")          # trimmed + upper-cased
        self.assertEqual(clean["category"], "Taps")      # title-cased
        self.assertEqual(clean["unit_price"], 10.0)      # rounded to 2dp

    def test_missing_and_negative_values_are_rejected(self):
        _, errors = s.validate_product({"sku": "", "name": "X", "category": "Y",
                                        "quantity": "-1", "reorder_level": "abc", "unit_price": "1"})
        self.assertEqual(len(errors), 3)


class StockMovementTests(BaseTest):
    def test_stock_in_and_out_update_quantity_and_history(self):
        pid = self.add(qty=10)
        self.assertEqual(s.record_movement(pid, 5, "Delivery"), 15)
        self.assertEqual(s.record_movement(pid, -12, "Customer order"), 3)
        # opening stock + 2 movements = 3 history rows
        self.assertEqual(len(s.get_movements(pid)), 3)

    def test_stock_cannot_go_below_zero(self):
        pid = self.add(qty=4)
        with self.assertRaises(s.StockError):
            s.record_movement(pid, -5, "Too many")
        self.assertEqual(s.get_product(pid)["quantity"], 4)   # unchanged

    def test_reason_is_required(self):
        pid = self.add()
        with self.assertRaises(s.StockError):
            s.record_movement(pid, 1, "   ")


class CsvTests(BaseTest):
    def test_import_sample_file(self):
        with open(SAMPLE, newline="", encoding="utf-8") as f:
            result = s.import_products_csv(f)
        self.assertEqual(result, {"added": 15, "updated": 0, "errors": []})

    def test_reimport_updates_and_logs_difference(self):
        self.add(sku="BTH-1", qty=10)
        csv_text = "sku,name,category,quantity,reorder_level,unit_price\nBTH-1,New Name,Taps,7,5,3\n"
        result = s.import_products_csv(io.StringIO(csv_text))
        self.assertEqual(result["updated"], 1)
        p = s.get_products(search="BTH-1")[0]
        self.assertEqual((p["name"], p["quantity"]), ("New Name", 7))
        self.assertEqual(s.get_movements(p["id"])[0]["change"], -3)

    def test_bad_rows_are_skipped_with_row_numbers(self):
        csv_text = ("sku,name,category,quantity,reorder_level,unit_price\n"
                    "OK-1,Good,Taps,1,1,1\n"
                    "BAD-1,Bad,Taps,minus,1,1\n")
        result = s.import_products_csv(io.StringIO(csv_text))
        self.assertEqual(result["added"], 1)
        self.assertTrue(result["errors"][0].startswith("Row 3:"))

    def test_missing_columns_are_reported(self):
        with self.assertRaises(s.StockError) as ctx:
            s.import_products_csv(io.StringIO("sku,name\nA,B\n"))
        self.assertIn("unit_price", str(ctx.exception))

    def test_export_flags_low_stock(self):
        self.add(sku="LOW-1", qty=2, reorder=5)
        self.add(sku="OK-1", qty=50, reorder=5)
        lines = s.export_products_csv().strip().splitlines()
        self.assertTrue(lines[0].startswith("sku,name"))
        self.assertIn("LOW", next(l for l in lines if l.startswith("LOW-1")))


class DashboardTests(BaseTest):
    def test_totals(self):
        self.add(sku="A", qty=10, reorder=5, price=2)    # value 20
        self.add(sku="B", qty=1, reorder=5, price=100)   # value 100, low
        t = s.dashboard_stats()["totals"]
        self.assertEqual((t["products"], t["units"], t["value"], t["low"]), (2, 11, 120, 1))


class PageTests(BaseTest):
    """Check the web pages work end-to-end through Flask's test client."""

    def test_pages_load(self):
        pid = self.add()
        for url in ["/", "/products", "/products/new", f"/products/{pid}",
                    f"/products/{pid}/edit", "/import", "/export.csv"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_unknown_product_is_404(self):
        self.assertEqual(self.client.get("/products/999").status_code, 404)

    def test_add_product_via_form(self):
        r = self.client.post("/products/new", data={
            "sku": "new-1", "name": "Form Tap", "category": "taps",
            "quantity": "3", "reorder_level": "1", "unit_price": "5"}, follow_redirects=True)
        self.assertIn(b"Added Form Tap", r.data)

    def test_duplicate_sku_rejected(self):
        self.add(sku="DUP-1")
        r = self.client.post("/products/new", data={
            "sku": "dup-1", "name": "X", "category": "Y",
            "quantity": "1", "reorder_level": "1", "unit_price": "1"})
        self.assertIn(b"already exists", r.data)

    def test_stock_out_too_many_shows_error(self):
        pid = self.add(qty=2)
        r = self.client.post(f"/products/{pid}/movement", data={
            "direction": "out", "quantity": "5", "reason": "Order"}, follow_redirects=True)
        self.assertIn(b"Not enough stock", r.data)

    def test_csv_upload(self):
        with open(SAMPLE, "rb") as f:
            r = self.client.post("/import", data={"file": (f, "products.csv")},
                                 content_type="multipart/form-data")
        self.assertIn(b"15 added", r.data)

    def test_low_filter(self):
        self.add(sku="LOW-1", name="Low Item", qty=1, reorder=5)
        self.add(sku="OK-1", name="Fine Item", qty=50, reorder=5)
        r = self.client.get("/products?low=1")
        self.assertIn(b"Low Item", r.data)
        self.assertNotIn(b"Fine Item", r.data)


if __name__ == "__main__":
    unittest.main()

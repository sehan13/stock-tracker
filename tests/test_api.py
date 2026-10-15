"""
Tests for the JSON REST API (/api/...).

Run with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_app import BaseTest      # noqa: E402  (reuses the temporary-database setup)

NEW = {"sku": "api-1", "name": "API Tap", "category": "taps",
       "quantity": 5, "reorder_level": 2, "unit_price": 10}


class ApiProductTests(BaseTest):
    def test_list_products_returns_json(self):
        self.add(sku="A-1", name="Alpha")
        r = self.client.get("/api/products")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()[0]["sku"], "A-1")

    def test_list_low_stock_filter(self):
        self.add(sku="LOW", qty=1, reorder=5)
        self.add(sku="OK", qty=50, reorder=5)
        skus = [p["sku"] for p in self.client.get("/api/products?low=1").get_json()]
        self.assertEqual(skus, ["LOW"])

    def test_get_one_product_includes_movements(self):
        pid = self.add(qty=3)
        body = self.client.get(f"/api/products/{pid}").get_json()
        self.assertEqual(body["quantity"], 3)
        self.assertEqual(body["movements"][0]["reason"], "Opening stock")

    def test_missing_product_is_json_404(self):
        r = self.client.get("/api/products/999")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())

    def test_create_product(self):
        r = self.client.post("/api/products", json=NEW)
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual((body["sku"], body["category"], body["stock_value"]), ("API-1", "Taps", 50.0))

    def test_create_rejects_invalid_data(self):
        r = self.client.post("/api/products", json={"sku": "", "unit_price": -1})
        self.assertEqual(r.status_code, 400)
        self.assertTrue(len(r.get_json()["details"]) >= 2)

    def test_create_rejects_non_json(self):
        r = self.client.post("/api/products", data="not json", content_type="text/plain")
        self.assertEqual(r.status_code, 400)

    def test_duplicate_sku_is_409(self):
        self.client.post("/api/products", json=NEW)
        self.assertEqual(self.client.post("/api/products", json=NEW).status_code, 409)

    def test_patch_updates_only_sent_fields(self):
        pid = self.add(sku="P-1", name="Old", price=5)
        r = self.client.patch(f"/api/products/{pid}", json={"name": "New"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.get_json()["name"], r.get_json()["unit_price"]), ("New", 5))

    def test_patch_cannot_change_quantity(self):
        pid = self.add()
        r = self.client.patch(f"/api/products/{pid}", json={"quantity": 999})
        self.assertEqual(r.status_code, 400)

    def test_delete(self):
        pid = self.add()
        self.assertEqual(self.client.delete(f"/api/products/{pid}").status_code, 204)
        self.assertEqual(self.client.get(f"/api/products/{pid}").status_code, 404)


class ApiMovementTests(BaseTest):
    def test_stock_out(self):
        pid = self.add(qty=10)
        r = self.client.post(f"/api/products/{pid}/movements", json={"change": -4, "reason": "Order"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["quantity"], 6)

    def test_cannot_go_below_zero(self):
        pid = self.add(qty=2)
        r = self.client.post(f"/api/products/{pid}/movements", json={"change": -5, "reason": "Order"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Not enough stock", r.get_json()["error"])

    def test_change_must_be_whole_number(self):
        pid = self.add()
        for bad in ["5", 2.5, True, None]:
            r = self.client.post(f"/api/products/{pid}/movements", json={"change": bad, "reason": "x"})
            self.assertEqual(r.status_code, 400, bad)


class ApiStatsTests(BaseTest):
    def test_stats(self):
        self.add(sku="A", qty=10, reorder=5, price=2, category="Taps")
        self.add(sku="B", qty=1, reorder=5, price=100, category="Baths")
        body = self.client.get("/api/stats").get_json()
        self.assertEqual((body["products"], body["units"], body["stock_value"], body["low_stock_count"]),
                         (2, 11, 120.0, 1))
        self.assertEqual(body["by_category"][0]["category"], "Baths")   # highest value first

    def test_wrong_method_is_json_405(self):
        r = self.client.put("/api/stats")
        self.assertEqual(r.status_code, 405)
        self.assertIn("error", r.get_json())


if __name__ == "__main__":
    unittest.main()

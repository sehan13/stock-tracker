-- Database schema for Stock Tracker (SQLite)

DROP TABLE IF EXISTS movements;
DROP TABLE IF EXISTS products;

-- One row per product we stock
CREATE TABLE products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT    NOT NULL UNIQUE,          -- stock keeping unit, e.g. "BTH-001"
    name          TEXT    NOT NULL,
    category      TEXT    NOT NULL,
    quantity      INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 10 CHECK (reorder_level >= 0),
    unit_price    REAL    NOT NULL DEFAULT 0 CHECK (unit_price >= 0),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Every stock change is recorded here (an audit trail)
CREATE TABLE movements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    change      INTEGER NOT NULL,                   -- positive = stock in, negative = stock out
    reason      TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_movements_product ON movements(product_id);

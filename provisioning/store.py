"""SQLite system of record: orders, tenants, entitlements, approvals, exceptions, audit log."""
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, account_id TEXT, status TEXT NOT NULL,
    payload TEXT, received_at TEXT NOT NULL, completed_at TEXT, automated INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY, account_id TEXT UNIQUE NOT NULL, region TEXT, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, order_id TEXT NOT NULL,
    sku TEXT NOT NULL, seats INTEGER NOT NULL CHECK (seats > 0),
    start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL,
    UNIQUE (order_id, sku)
);
CREATE TABLE IF NOT EXISTS approvals (
    order_id TEXT, queue TEXT, reason TEXT, status TEXT DEFAULT 'PENDING', decided_by TEXT
);
CREATE TABLE IF NOT EXISTS exceptions (order_id TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS audit_log (ts TEXT, order_id TEXT, action TEXT, detail TEXT);
"""


class Store:
    def __init__(self, path=":memory:"):
        # check_same_thread=False: the webhook server handles requests in worker threads
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def q(self, sql, *args):
        return self.db.execute(sql, args).fetchall()

    def one(self, sql, *args):
        return self.db.execute(sql, args).fetchone()

    def run(self, sql, *args):
        with self.db:  # one transaction per write
            self.db.execute(sql, args)

    def audit(self, ts, order_id, action, detail=""):
        self.run("INSERT INTO audit_log VALUES (?,?,?,?)", ts, order_id, action, detail)

    def upsert_order(self, order_id, account_id, status, payload, ts):
        self.run(
            "INSERT INTO orders (order_id, account_id, status, payload, received_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(order_id) DO UPDATE SET status=excluded.status",
            order_id, account_id, status, json.dumps(payload), ts,
        )

    def set_status(self, order_id, status, ts=None, automated=None):
        self.run(
            "UPDATE orders SET status=?, completed_at=COALESCE(?, completed_at), "
            "automated=COALESCE(?, automated) WHERE order_id=?",
            status, ts, automated, order_id,
        )

    def order(self, order_id):
        return self.one("SELECT * FROM orders WHERE order_id=?", order_id)

    def tenant_for(self, account_id):
        return self.one("SELECT * FROM tenants WHERE account_id=? AND status='ACTIVE'", account_id)

    def active_entitlements(self, tenant_id=None):
        if tenant_id:
            return self.q("SELECT * FROM entitlements WHERE status='ACTIVE' AND tenant_id=?", tenant_id)
        return self.q("SELECT * FROM entitlements WHERE status='ACTIVE'")

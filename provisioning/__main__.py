"""Demo: python -m provisioning [--serve]

Runs the whole lifecycle on synthetic Salesforce orders and prints the leadership report.
With --serve it starts the webhook endpoint on :8080 instead.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from .console import FakeConsole
from .reports import automation_report, exception_queue
from .store import Store
from .webhook import make_server
from .workflow import Engine

DATA = Path(__file__).resolve().parent.parent / "data" / "sample_orders.json"


class SimClock:
    """Simulated time so the demo can show SLA and approval delays."""
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def demo():
    clock = SimClock(datetime(2026, 11, 20, 9, 0))
    console = FakeConsole()
    engine = Engine(Store(), console, clock=clock)

    console.fail_next["set_license"] = 2  # first two console calls time out -> retry recovers
    print("== 1. Intake of Salesforce Closed Won orders")
    for payload in json.loads(DATA.read_text()):
        res = engine.handle_salesforce_event(payload)
        print("  ", res)
        clock.advance(minutes=3)

    print("== 2. Same webhook delivered twice (idempotency)")
    print("  ", engine.handle_salesforce_event(json.loads(DATA.read_text())[0]))

    print("== 3. Deal desk approves the non-standard order 6 hours later")
    clock.advance(hours=6)
    print("  ", engine.approve("006A004", approver="deal.desk@example.com"))

    print("== 4. Legacy SKU migration:", engine.migrate_legacy_skus(), "entitlement(s) moved")
    print("== 5. Nightly job on 2026-11-25: term ended ->", engine.deprovision_expired(date(2026, 11, 25)))
    print("== 6. Reconciliation drift:", engine.reconcile() or "none")
    print("== 7. Exception queue:")
    for e in exception_queue(engine.store):
        print("   ", e)
    print("== 8. Leadership report")
    for k, v in automation_report(engine.store).items():
        print(f"    {k:28} {v}")


def serve():
    engine = Engine(Store(os.environ.get("DB_PATH", "provisioning.db")), FakeConsole())
    secret = os.environ.get("WEBHOOK_SECRET", "dev-secret").encode()
    server = make_server(engine, secret, host="0.0.0.0", port=8080)
    print("Listening on :8080  POST /webhooks/salesforce")
    server.serve_forever()


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else demo()

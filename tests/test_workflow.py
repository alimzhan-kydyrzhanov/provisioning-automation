import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from provisioning.console import TransientError, with_retry
from provisioning.reports import automation_report
from provisioning.webhook import make_server, sign


def statuses(engine):
    return {r["order_id"]: r["status"] for r in engine.store.q("SELECT order_id, status FROM orders")}


def test_standard_order_is_provisioned_end_to_end(engine, orders):
    res = engine.handle_salesforce_event(orders[0])
    assert res["status"] == "PROVISIONED"
    assert engine.console.licenses[("tn-001acme", "ENDPOINT-CORE")] == 250
    assert engine.reconcile() == []


def test_duplicate_webhook_does_not_provision_twice(engine, orders):
    engine.handle_salesforce_event(orders[0])
    calls = engine.console.calls
    res = engine.handle_salesforce_event(orders[0])
    assert res["duplicate"] is True
    assert engine.console.calls == calls
    assert engine.store.one("SELECT COUNT(*) c FROM entitlements")["c"] == 2


def test_invalid_order_goes_to_exception_queue_not_dropped(engine, orders):
    res = engine.handle_salesforce_event(orders[5])
    assert res["status"] == "EXCEPTION"
    assert "unknown SKU" in engine.store.one("SELECT reason FROM exceptions")["reason"]
    assert engine.console.licenses == {}


def test_non_standard_order_waits_for_approval_then_provisions(engine, orders):
    assert engine.handle_salesforce_event(orders[3])["status"] == "PENDING_APPROVAL"
    assert engine.console.licenses == {}
    assert engine.approve("006A004", "deal.desk@example.com")["status"] == "PROVISIONED"
    assert automation_report(engine.store)["provisioned_after_approval"] == 1


def test_rejected_order_is_never_provisioned(engine, orders):
    engine.handle_salesforce_event(orders[3])
    engine.reject("006A004", "deal.desk@example.com", "discount not approved")
    with pytest.raises(ValueError):
        engine.approve("006A004", "someone")
    assert statuses(engine)["006A004"] == "REJECTED"


def test_transient_console_errors_are_retried(engine, orders):
    engine.console.fail_next["set_license"] = 2
    assert engine.handle_salesforce_event(orders[0])["status"] == "PROVISIONED"


def test_persistent_console_error_becomes_exception(engine, orders):
    engine.console.fail_next["create_tenant"] = 5
    res = engine.handle_salesforce_event(orders[0])
    assert res["status"] == "EXCEPTION" and "after 3 retries" in res["reason"]


def test_retry_backoff_delays():
    delays, attempts = [], iter([TransientError(), TransientError(), "ok"])
    def fn():
        x = next(attempts)
        if isinstance(x, Exception):
            raise x
        return x
    assert with_retry(fn, attempts=3, base_delay=1.0, sleep=delays.append) == "ok"
    assert delays == [1.0, 2.0]


def test_trial_is_converted_when_paid_order_arrives(engine, orders):
    engine.handle_salesforce_event(orders[1])  # trial
    engine.handle_salesforce_event(orders[2])  # paid, same product
    trial = engine.store.one("SELECT status FROM entitlements WHERE sku='ENDPOINT-TRIAL'")
    assert trial["status"] == "CONVERTED"
    assert ("tn-001nova", "ENDPOINT-TRIAL") not in engine.console.licenses


def test_expired_term_revokes_access_and_closes_tenant(engine, orders):
    engine.handle_salesforce_event(orders[7])  # ends 2026-11-25
    res = engine.deprovision_expired(date(2026, 11, 25))
    assert res == {"seats_reclaimed": 30, "tenants_closed": ["tn-001shrt"]}
    assert engine.console.licenses == {}


def test_legacy_sku_migration_keeps_seats(engine, orders):
    engine.handle_salesforce_event(orders[6])
    assert engine.migrate_legacy_skus() == 1
    assert engine.console.licenses == {("tn-001oldp", "ENDPOINT-CORE"): 80}
    assert engine.reconcile() == []


def test_reconcile_detects_manual_change_in_console(engine, orders):
    engine.handle_salesforce_event(orders[0])
    engine.console.licenses[("tn-001acme", "ENDPOINT-CORE")] = 999  # someone edited the console by hand
    assert engine.reconcile() == [{"tenant_id": "tn-001acme", "sku": "ENDPOINT-CORE", "expected": 250, "console": 999}]


def test_report_numbers(engine, orders, clock):
    for o in orders:
        engine.handle_salesforce_event(o)
    clock.advance(hours=6)
    engine.approve("006A004", "lead")
    r = automation_report(engine.store)
    assert (r["orders_total"], r["auto_provisioned"], r["exceptions"]) == (8, 5, 2)
    assert r["automation_coverage_pct"] == 62.5
    assert r["sla_met_pct"] == 83.3  # the approved order missed the 4h SLA


def test_webhook_requires_valid_signature(engine, orders):
    server = make_server(engine, b"s3cret", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/webhooks/salesforce"
    body = json.dumps(orders[0]).encode()
    try:
        bad = urllib.request.Request(url, body, {"X-Signature": "nope"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 401
        good = urllib.request.Request(url, body, {"X-Signature": sign(b"s3cret", body)})
        with urllib.request.urlopen(good) as resp:
            assert resp.status == 202
            assert json.loads(resp.read())["status"] == "PROVISIONED"
    finally:
        server.shutdown()

"""Leadership report: automation coverage, time saved, error rate, SLA."""
from datetime import datetime

from .catalog import MANUAL_MINUTES_PER_ORDER, SLA_HOURS


def automation_report(store):
    total = store.one("SELECT COUNT(*) c FROM orders")["c"]
    auto = store.one("SELECT COUNT(*) c FROM orders WHERE status='PROVISIONED' AND automated=1")["c"]
    manual = store.one("SELECT COUNT(*) c FROM orders WHERE status='PROVISIONED' AND automated=0")["c"]
    exceptions = store.one("SELECT COUNT(*) c FROM orders WHERE status='EXCEPTION'")["c"]
    pending = store.one("SELECT COUNT(*) c FROM orders WHERE status='PENDING_APPROVAL'")["c"]

    done = store.q("SELECT received_at, completed_at FROM orders WHERE status='PROVISIONED'")
    within_sla = sum(
        1 for r in done
        if (datetime.fromisoformat(r["completed_at"]) - datetime.fromisoformat(r["received_at"])).total_seconds()
        <= SLA_HOURS * 3600
    )
    pct = lambda a, b: round(100 * a / b, 1) if b else 0.0
    return {
        "orders_total": total,
        "auto_provisioned": auto,
        "provisioned_after_approval": manual,
        "pending_approval": pending,
        "exceptions": exceptions,
        "automation_coverage_pct": pct(auto, total),
        "error_rate_pct": pct(exceptions, total),
        "time_saved_hours": round(auto * MANUAL_MINUTES_PER_ORDER / 60, 1),
        "sla_met_pct": pct(within_sla, len(done)),
    }


def exception_queue(store):
    return [dict(r) for r in store.q("SELECT order_id, reason FROM exceptions ORDER BY created_at")]

"""The provisioning workflow engine: provision, approval routing, exceptions, deprovision, migration."""
import calendar
import json
from datetime import date, datetime

from .catalog import MIGRATIONS, SKUS, approval_reasons
from .console import TransientError, with_retry
from .salesforce import OrderValidationError, parse_order


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


class Engine:
    def __init__(self, store, console, clock=datetime.utcnow, retry_delay=0.0):
        self.store, self.console, self.clock, self.retry_delay = store, console, clock, retry_delay

    def _ts(self):
        return self.clock().isoformat(timespec="seconds")

    def _call(self, fn):
        return with_retry(fn, attempts=3, base_delay=self.retry_delay)

    def _exception(self, order_id, reason):
        """Exception routing: never drop a bad order silently; park it with the reason."""
        self.store.set_status(order_id, "EXCEPTION")
        self.store.run("INSERT INTO exceptions VALUES (?,?,?)", order_id, reason, self._ts())
        self.store.audit(self._ts(), order_id, "exception", reason)
        return {"order_id": order_id, "status": "EXCEPTION", "reason": reason}

    # ---------- intake ----------
    def handle_salesforce_event(self, payload: dict) -> dict:
        opp = payload.get("opportunity") or {}
        order_id = opp.get("Id") or "UNKNOWN"
        existing = self.store.order(order_id)
        if existing and existing["status"] in ("PROVISIONED", "PENDING_APPROVAL"):
            self.store.audit(self._ts(), order_id, "duplicate_ignored")
            return {"order_id": order_id, "status": existing["status"], "duplicate": True}

        self.store.upsert_order(order_id, (opp.get("Account") or {}).get("Id"), "RECEIVED", payload, self._ts())
        self.store.audit(self._ts(), order_id, "received")
        try:
            order = parse_order(payload)
        except OrderValidationError as e:
            return self._exception(order_id, "validation: " + "; ".join(e.reasons))

        reasons = approval_reasons(order)
        if reasons:
            for queue, reason in reasons:
                self.store.run("INSERT INTO approvals (order_id, queue, reason) VALUES (?,?,?)", order_id, queue, reason)
            self.store.set_status(order_id, "PENDING_APPROVAL")
            self.store.audit(self._ts(), order_id, "routed_for_approval", "; ".join(r for _, r in reasons))
            return {"order_id": order_id, "status": "PENDING_APPROVAL", "queues": sorted({q for q, _ in reasons})}
        return self._provision(order, automated=True)

    def approve(self, order_id, approver):
        row = self.store.order(order_id)
        if not row or row["status"] != "PENDING_APPROVAL":
            raise ValueError(f"{order_id} is not waiting for approval")
        self.store.run("UPDATE approvals SET status='APPROVED', decided_by=? WHERE order_id=?", approver, order_id)
        self.store.audit(self._ts(), order_id, "approved", approver)
        return self._provision(parse_order(json.loads(row["payload"])), automated=False)

    def reject(self, order_id, approver, reason):
        self.store.run("UPDATE approvals SET status='REJECTED', decided_by=? WHERE order_id=?", approver, order_id)
        self.store.set_status(order_id, "REJECTED", self._ts())
        self.store.audit(self._ts(), order_id, "rejected", f"{approver}: {reason}")

    # ---------- provisioning ----------
    def _provision(self, order, automated):
        try:
            tenant = self.store.tenant_for(order.account_id)
            if tenant:
                tenant_id = tenant["tenant_id"]
            else:
                tenant_id = self._call(lambda: self.console.create_tenant(order.account_id, order.region))
                self.store.run("INSERT OR REPLACE INTO tenants VALUES (?,?,?, 'ACTIVE')",
                               tenant_id, order.account_id, order.region)
            end = add_months(order.start_date, order.term_months)
            for line in order.lines:
                self._call(lambda l=line: self.console.set_license(tenant_id, l.sku, l.quantity))
                self.store.run(
                    "INSERT OR IGNORE INTO entitlements (tenant_id, order_id, sku, seats, start_date, end_date, status) "
                    "VALUES (?,?,?,?,?,?, 'ACTIVE')",
                    tenant_id, order.order_id, line.sku, line.quantity, order.start_date.isoformat(), end.isoformat(),
                )
                if not SKUS[line.sku]["trial"]:
                    self._convert_trials(tenant_id, SKUS[line.sku]["product"], order.order_id)
        except TransientError as e:
            return self._exception(order.order_id, f"console error after 3 retries: {e}")
        self.store.set_status(order.order_id, "PROVISIONED", self._ts(), int(automated))
        self.store.audit(self._ts(), order.order_id, "provisioned", f"tenant={tenant_id}")
        return {"order_id": order.order_id, "status": "PROVISIONED", "tenant_id": tenant_id}

    def _convert_trials(self, tenant_id, product, order_id):
        """Trial -> paid conversion: a paid license replaces the trial of the same product."""
        for ent in self.store.active_entitlements(tenant_id):
            if SKUS[ent["sku"]]["trial"] and SKUS[ent["sku"]]["product"] == product:
                self._call(lambda e=ent: self.console.revoke_license(tenant_id, e["sku"]))
                self.store.run("UPDATE entitlements SET status='CONVERTED' WHERE id=?", ent["id"])
                self.store.audit(self._ts(), order_id, "trial_converted", ent["sku"])

    # ---------- reverse workflows ----------
    def deprovision_expired(self, today: date):
        """Term ended: revoke access, reclaim licenses, close tenants with nothing left."""
        reclaimed = 0
        for ent in self.store.active_entitlements():
            if date.fromisoformat(ent["end_date"]) <= today:
                self._call(lambda e=ent: self.console.revoke_license(e["tenant_id"], e["sku"]))
                self.store.run("UPDATE entitlements SET status='REVOKED' WHERE id=?", ent["id"])
                self.store.audit(self._ts(), ent["order_id"], "license_reclaimed", f"{ent['sku']} x{ent['seats']}")
                reclaimed += ent["seats"]
        closed = []
        for t in self.store.q("SELECT tenant_id FROM tenants WHERE status='ACTIVE'"):
            if not self.store.active_entitlements(t["tenant_id"]):
                self._call(lambda: self.console.close_tenant(t["tenant_id"]))
                self.store.run("UPDATE tenants SET status='CLOSED' WHERE tenant_id=?", t["tenant_id"])
                self.store.audit(self._ts(), None, "tenant_closed", t["tenant_id"])
                closed.append(t["tenant_id"])
        return {"seats_reclaimed": reclaimed, "tenants_closed": closed}

    def migrate_legacy_skus(self):
        """Move customers from old SKUs to new ones without changing seats or term."""
        moved = 0
        for ent in self.store.active_entitlements():
            new_sku = MIGRATIONS.get(ent["sku"])
            if not new_sku:
                continue
            self._call(lambda e=ent: self.console.set_license(e["tenant_id"], new_sku, e["seats"]))
            self._call(lambda e=ent: self.console.revoke_license(e["tenant_id"], e["sku"]))
            with self.store.db:
                self.store.db.execute("UPDATE entitlements SET status='MIGRATED' WHERE id=?", (ent["id"],))
                self.store.db.execute(
                    "INSERT OR IGNORE INTO entitlements (tenant_id, order_id, sku, seats, start_date, end_date, status) "
                    "VALUES (?,?,?,?,?,?, 'ACTIVE')",
                    (ent["tenant_id"], ent["order_id"], new_sku, ent["seats"], ent["start_date"], ent["end_date"]),
                )
            self.store.audit(self._ts(), ent["order_id"], "sku_migrated", f"{ent['sku']} -> {new_sku}")
            moved += 1
        return moved

    # ---------- compliance control ----------
    def reconcile(self):
        """Compare our entitlements with what the console actually grants. Any drift = finding."""
        expected = {(e["tenant_id"], e["sku"]): e["seats"] for e in self.store.active_entitlements()}
        actual = dict(self.console.licenses)
        drift = []
        for key in expected.keys() | actual.keys():
            if expected.get(key) != actual.get(key):
                drift.append({"tenant_id": key[0], "sku": key[1], "expected": expected.get(key), "console": actual.get(key)})
        return sorted(drift, key=lambda d: (d["tenant_id"], d["sku"]))

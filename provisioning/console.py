"""Client for the product console API (here: an in-memory fake) + retry with backoff."""
import time


class TransientError(Exception):
    """Temporary failure (timeout, 503). Safe to retry."""


def with_retry(fn, attempts=3, base_delay=0.0, sleep=time.sleep):
    """Call fn(); on TransientError retry with exponential backoff (base, 2*base, 4*base...)."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TransientError:
            if attempt == attempts:
                raise
            sleep(base_delay * 2 ** (attempt - 1))


class FakeConsole:
    """Simulates the product console. fail_next[op] = N makes the next N calls of op fail."""

    def __init__(self):
        self.tenants = {}   # tenant_id -> {"account_id", "region"}
        self.licenses = {}  # (tenant_id, sku) -> seats
        self.fail_next = {}
        self.calls = 0

    def _maybe_fail(self, op):
        self.calls += 1
        if self.fail_next.get(op, 0) > 0:
            self.fail_next[op] -= 1
            raise TransientError(f"{op}: 503 Service Unavailable")

    def create_tenant(self, account_id, region):
        self._maybe_fail("create_tenant")
        tenant_id = f"tn-{account_id.lower()}"
        self.tenants.setdefault(tenant_id, {"account_id": account_id, "region": region})
        return tenant_id

    def set_license(self, tenant_id, sku, seats):
        self._maybe_fail("set_license")
        self.licenses[(tenant_id, sku)] = seats

    def revoke_license(self, tenant_id, sku):
        self._maybe_fail("revoke_license")
        self.licenses.pop((tenant_id, sku), None)

    def close_tenant(self, tenant_id):
        self._maybe_fail("close_tenant")
        self.tenants.pop(tenant_id, None)

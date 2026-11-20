"""Parse and validate a (simulated) Salesforce 'Opportunity Closed Won' webhook payload."""
from dataclasses import dataclass, field
from datetime import date

from .catalog import REGIONS, SKUS


class OrderValidationError(ValueError):
    def __init__(self, order_id, reasons):
        super().__init__("; ".join(reasons))
        self.order_id = order_id
        self.reasons = reasons


@dataclass(frozen=True)
class OrderLine:
    sku: str
    quantity: int


@dataclass(frozen=True)
class Order:
    order_id: str
    account_id: str
    account_name: str
    region: str
    start_date: date
    term_months: int
    discount_pct: float
    admin_email: str
    lines: list = field(default_factory=list)


def parse_order(payload: dict) -> Order:
    """Turn a webhook payload into an Order or raise OrderValidationError with ALL problems found."""
    opp = payload.get("opportunity") or {}
    order_id = opp.get("Id") or "UNKNOWN"
    account = opp.get("Account") or {}
    errors = []

    if payload.get("event") != "Opportunity.ClosedWon" or opp.get("StageName") != "Closed Won":
        errors.append("not a Closed Won opportunity")
    for key in ("Id", "ContractStartDate", "TermMonths", "AdminEmail"):
        if opp.get(key) in (None, ""):
            errors.append(f"missing {key}")
    if not account.get("Id"):
        errors.append("missing Account.Id")
    if account.get("Region") not in REGIONS:
        errors.append(f"unknown region {account.get('Region')!r}")
    if opp.get("AdminEmail") and "@" not in str(opp["AdminEmail"]):
        errors.append("invalid AdminEmail")

    start = None
    try:
        start = date.fromisoformat(str(opp.get("ContractStartDate")))
    except ValueError:
        errors.append(f"invalid ContractStartDate {opp.get('ContractStartDate')!r}")

    lines = []
    items = opp.get("LineItems") or []
    if not items:
        errors.append("no line items")
    for item in items:
        sku, qty = item.get("SKU"), item.get("Quantity")
        if sku not in SKUS:
            errors.append(f"unknown SKU {sku!r}")
        elif not isinstance(qty, int) or qty <= 0:
            errors.append(f"{sku}: quantity must be a positive integer")
        else:
            lines.append(OrderLine(sku, qty))

    if errors:
        raise OrderValidationError(order_id, errors)
    return Order(
        order_id=order_id,
        account_id=account["Id"],
        account_name=account.get("Name", ""),
        region=account["Region"],
        start_date=start,
        term_months=int(opp["TermMonths"]),
        discount_pct=float(opp.get("DiscountPct", 0)),
        admin_email=opp["AdminEmail"],
        lines=lines,
    )

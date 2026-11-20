"""Product catalog and business rules (all product names are fictional)."""

# SKU -> what it unlocks in the product console
SKUS = {
    "ENDPOINT-CORE": {"product": "endpoint", "trial": False},
    "ENDPOINT-LEGACY": {"product": "endpoint", "trial": False},  # old SKU, migrated to ENDPOINT-CORE
    "CLOUD-POSTURE": {"product": "cloud", "trial": False},
    "IDENTITY-PROTECT": {"product": "identity", "trial": False},
    "ENDPOINT-TRIAL": {"product": "endpoint", "trial": True},
}

# Conversion / migration map: old SKU -> new SKU
MIGRATIONS = {"ENDPOINT-LEGACY": "ENDPOINT-CORE"}

STANDARD_TERMS_MONTHS = {1, 12, 24, 36}  # 1 month only for trials
MAX_STANDARD_SEATS = 5000
MAX_STANDARD_DISCOUNT_PCT = 30
REGIONS = {"EU", "US", "APAC"}

# Assumption used for "time saved" reporting: how long one order takes by hand
MANUAL_MINUTES_PER_ORDER = 25
SLA_HOURS = 4


def approval_reasons(order):
    """Return (queue, reason) pairs for non-standard orders. Empty list = standard order."""
    reasons = []
    if order.discount_pct > MAX_STANDARD_DISCOUNT_PCT:
        reasons.append(("deal_desk", f"discount {order.discount_pct}% > {MAX_STANDARD_DISCOUNT_PCT}%"))
    if order.term_months not in STANDARD_TERMS_MONTHS:
        reasons.append(("deal_desk", f"non-standard term {order.term_months} months"))
    for line in order.lines:
        if line.quantity > MAX_STANDARD_SEATS:
            reasons.append(("provisioning_lead", f"{line.sku}: {line.quantity} seats > {MAX_STANDARD_SEATS}"))
    return reasons

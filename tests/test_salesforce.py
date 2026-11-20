import pytest

from provisioning.catalog import approval_reasons
from provisioning.salesforce import OrderValidationError, parse_order
from provisioning.workflow import add_months
from datetime import date


def test_valid_order_is_parsed(orders):
    order = parse_order(orders[0])
    assert order.order_id == "006A001"
    assert [(l.sku, l.quantity) for l in order.lines] == [("ENDPOINT-CORE", 250), ("IDENTITY-PROTECT", 250)]


def test_all_validation_errors_are_reported_at_once(orders):
    with pytest.raises(OrderValidationError) as e:
        parse_order(orders[4])
    assert "missing AdminEmail" in e.value.reasons
    assert any("ContractStartDate" in r for r in e.value.reasons)


def test_not_closed_won_is_rejected(orders):
    orders[0]["opportunity"]["StageName"] = "Negotiation"
    with pytest.raises(OrderValidationError):
        parse_order(orders[0])


@pytest.mark.parametrize("qty", [0, -5, "10"])
def test_bad_quantity(orders, qty):
    orders[0]["opportunity"]["LineItems"][0]["Quantity"] = qty
    with pytest.raises(OrderValidationError):
        parse_order(orders[0])


def test_standard_order_needs_no_approval(orders):
    assert approval_reasons(parse_order(orders[0])) == []


def test_non_standard_order_goes_to_two_queues(orders):
    queues = {q for q, _ in approval_reasons(parse_order(orders[3]))}
    assert queues == {"deal_desk", "provisioning_lead"}


def test_add_months_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 20), 12) == date(2027, 11, 20)

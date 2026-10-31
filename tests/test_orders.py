from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_support_agent.data import OrderItem, Promotion, load_store_data


def sample_data():
    """Build focused synthetic cases without changing shared CSV fixtures."""
    source = load_store_data(Path(__file__).parent / "fixtures" / "data")
    return replace(
        source,
        customers=source.customers + (
            replace(source.customers[0], customer_id=303, name="Demo Customer Three", email="demo3@example.test"),
        ),
        products=(replace(source.products[0], price_brl=Decimal("1200.00")), source.products[1]),
        orders=(
            replace(source.orders[0], order_id=403, status="cancelled", notes="Demo cancellation note"),
            replace(source.orders[1], status="confirmed"),
            replace(source.orders[0], status="delivered", total_brl=Decimal("900.000")),
        ),
        order_items=(
            OrderItem(order_id=401, quantity=3, product_id=102),
            OrderItem(order_id=402, quantity=1, product_id=101),
            OrderItem(order_id=401, quantity=2, product_id=101),
            OrderItem(order_id=403, quantity=4, product_id=102),
            OrderItem(order_id=401, quantity=1, product_id=102),
        ),
    )


def test_owner_can_read_order():
    from emporio_support_agent.orders import OrderView, get_order_for_customer

    view = get_order_for_customer(sample_data(), customer_id=301, order_id=401)
    assert isinstance(view, OrderView)
    assert view.order_id == 401
    assert view.order_date == date(2025, 2, 1)
    assert view.payment_method == "pix"


def test_foreign_and_missing_orders_are_indistinguishable():
    from emporio_support_agent.orders import get_order_for_customer

    data = sample_data()
    foreign = get_order_for_customer(data, customer_id=301, order_id=402)
    missing = get_order_for_customer(data, customer_id=301, order_id=999)
    assert foreign is missing is None
    assert get_order_for_customer(data, customer_id=999, order_id=401) is None


def test_unauthorized_order_items_are_never_resolved():
    from emporio_support_agent.orders import get_order_for_customer

    # An inaccessible record must not trigger item errors that reveal its existence.
    data = replace(sample_data(), products=())
    assert get_order_for_customer(data, customer_id=301, order_id=402) is None
    assert get_order_for_customer(data, customer_id=301, order_id=999) is None


@pytest.mark.parametrize("identifier", [0, -1, True, False, "401", 12.0, None, Decimal("401")])
@pytest.mark.parametrize("field", ["customer_id", "order_id"])
def test_lookup_rejects_invalid_identifiers(identifier, field):
    from emporio_support_agent.orders import get_order_for_customer

    arguments = {"customer_id": 301, "order_id": 401, field: identifier}
    with pytest.raises(ValueError, match=rf"{field} must be a positive integer"):
        get_order_for_customer(sample_data(), **arguments)


@pytest.mark.parametrize("identifier", [0, -1, True, False, "301", 12.0, None, Decimal("301")])
def test_listing_rejects_invalid_customer_identifiers(identifier):
    from emporio_support_agent.orders import list_orders_for_customer

    with pytest.raises(ValueError, match="customer_id must be a positive integer"):
        list_orders_for_customer(sample_data(), customer_id=identifier)


def test_listings_are_owner_scoped_and_preserve_source_order():
    from emporio_support_agent.orders import list_orders_for_customer

    data = sample_data()
    first = list_orders_for_customer(data, customer_id=301)
    second = list_orders_for_customer(data, customer_id=302)
    assert isinstance(first, tuple)
    assert tuple(view.order_id for view in first) == (403, 401)
    assert tuple(view.order_id for view in second) == (402,)
    assert list_orders_for_customer(data, customer_id=303) == ()
    assert list_orders_for_customer(data, customer_id=999) == ()
    assert first[0].status == "cancelled"
    assert first[0].notes == "Demo cancellation note"


def test_historical_total_is_decimal_and_never_repriced():
    from emporio_support_agent.orders import get_order_for_customer

    data = sample_data()
    data = replace(data, order_items=(OrderItem(order_id=401, quantity=1, product_id=101),))
    view = get_order_for_customer(data, customer_id=301, order_id=401)
    assert data.products[0].price_brl == Decimal("1200.00")
    assert isinstance(view.historical_total_brl, Decimal)
    assert view.historical_total_brl.as_tuple() == Decimal("900.000").as_tuple()

    changed_catalog = replace(
        data,
        products=tuple(replace(p, price_brl=Decimal("9999.99")) for p in data.products),
        promotions=(Promotion(801, 101, 10, "Demo", True), Promotion(802, 101, 80, "Demo", True)),
    )
    assert get_order_for_customer(changed_catalog, customer_id=301, order_id=401) == view


@pytest.mark.parametrize("status", ["pending", "confirmed", "shipped", "delivered", "cancelled", "future_status"])
def test_status_and_estimate_are_preserved_without_date_inference(status):
    from emporio_support_agent.orders import get_order_for_customer

    data = sample_data()
    data = replace(data, orders=(replace(data.orders[-1], status=status, estimated_delivery=date(2020, 1, 1)),))
    view = get_order_for_customer(data, customer_id=301, order_id=401)
    assert view.status == status
    assert view.estimated_delivery == date(2020, 1, 1)
    assert type(view.estimated_delivery) is date
    names = {field.name for field in fields(view)}
    assert not names.intersection({"received_at", "delivered_at", "delivery_date", "carrier"})


def test_missing_tracking_estimate_and_notes_remain_missing():
    from emporio_support_agent.orders import get_order_for_customer

    view = get_order_for_customer(sample_data(), customer_id=302, order_id=402)
    assert view.status == "confirmed"
    assert view.tracking_code is None
    assert view.estimated_delivery is None
    assert view.notes is None


def test_present_tracking_and_notes_remain_exact_source_values():
    from emporio_support_agent.orders import get_order_for_customer

    data = sample_data()
    notes = "  Demo cancellation reason\nwith unchanged spacing.  "
    data = replace(data, orders=(replace(data.orders[0], notes=notes),))
    view = get_order_for_customer(data, customer_id=301, order_id=403)
    assert view.status == "cancelled"
    assert view.tracking_code == "DEMO-TRACK-ONE"
    assert view.notes == notes


def test_items_keep_names_quantities_order_and_repeated_product_rows():
    from emporio_support_agent.orders import OrderItemView, get_order_for_customer

    data = sample_data()
    view = get_order_for_customer(data, customer_id=301, order_id=401)
    assert isinstance(view.items, tuple)
    assert view.items == (
        OrderItemView(product_id=102, product_name=data.products[1].name, quantity=3),
        OrderItemView(product_id=101, product_name=data.products[0].name, quantity=2),
        OrderItemView(product_id=102, product_name=data.products[1].name, quantity=1),
    )
    assert {field.name for field in fields(view.items[0])} == {"product_id", "product_name", "quantity"}
    single = get_order_for_customer(data, customer_id=302, order_id=402)
    assert len(single.items) == 1 and single.items[0].quantity == 1


def test_order_without_item_rows_gets_an_empty_tuple():
    from emporio_support_agent.orders import get_order_for_customer

    data = replace(sample_data(), order_items=())
    assert get_order_for_customer(data, customer_id=301, order_id=401).items == ()


def test_result_has_no_customer_identity_or_contact_fields():
    from emporio_support_agent.orders import get_order_for_customer

    data = sample_data()
    view = get_order_for_customer(data, customer_id=301, order_id=401)
    assert {field.name for field in fields(view)} == {
        "order_id", "order_date", "status", "historical_total_brl", "payment_method",
        "tracking_code", "estimated_delivery", "notes", "items",
    }
    serialized = repr(asdict(view))
    for customer in data.customers:
        for value in (customer.name, customer.phone, customer.email, customer.city):
            assert value not in serialized


def test_order_views_do_not_require_customer_directory_access():
    from emporio_support_agent.orders import get_order_for_customer, list_orders_for_customer

    data = replace(sample_data(), customers=())
    assert get_order_for_customer(data, customer_id=301, order_id=401).order_id == 401
    assert tuple(view.order_id for view in list_orders_for_customer(data, customer_id=301)) == (403, 401)


def test_views_are_immutable_and_source_data_is_unchanged():
    from emporio_support_agent.orders import get_order_for_customer, list_orders_for_customer

    data = sample_data()
    before = replace(data)
    view = get_order_for_customer(data, customer_id=301, order_id=401)
    with pytest.raises(FrozenInstanceError):
        view.status = "shipped"
    with pytest.raises(FrozenInstanceError):
        view.items[0].quantity = 999
    list_orders_for_customer(data, customer_id=301)
    assert data == before

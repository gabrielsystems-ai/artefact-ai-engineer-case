from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_support_agent.data import Category, load_store_data


@pytest.fixture
def data():
    source = load_store_data(Path(__file__).parent / "fixtures" / "data")
    product = source.products[0]
    return replace(
        source,
        categories=source.categories + (Category(20, "Demo keyboards", "Demo category"),),
        products=(
            replace(product, product_id=103, category_id=10, stock_quantity=5),
            replace(product, product_id=101, category_id=20, status="discontinued"),
            replace(product, product_id=102, category_id=10, status="coming_soon"),
            replace(product, product_id=104, category_id=20, stock_quantity=2),
        ),
    )


def test_category_lookup(data):
    from emporio_support_agent.catalog import get_category_by_id

    assert get_category_by_id(data, 10) is data.categories[0]
    assert get_category_by_id(data, 20) is data.categories[1]
    assert get_category_by_id(data, 999) is None


def test_product_lookup_preserves_original_record(data):
    from emporio_support_agent.catalog import get_product_by_id

    assert get_product_by_id(data, 102) is data.products[2]
    assert get_product_by_id(data, 999) is None


@pytest.mark.parametrize("filters,expected_ids", [
    ({}, (103, 101, 102, 104)),
    ({"category_id": 10}, (103, 102)),
    ({"status": "active"}, (103, 104)),
    ({"category_id": 20, "status": "active"}, (104,)),
    ({"category_id": 999}, ()),
    ({"status": "unknown"}, ()),
    ({"status": "ACTIVE"}, ()),
])
def test_filtering_uses_exact_filters_and_preserves_source_order(data, filters, expected_ids):
    from emporio_support_agent.catalog import filter_products

    result = filter_products(data, **filters)
    assert isinstance(result, tuple)
    assert tuple(p.product_id for p in result) == expected_ids
    assert all(any(p is original for original in data.products) for p in result)
    assert tuple(p.product_id for p in data.products) == (103, 101, 102, 104)


def test_default_availability_is_one_unit(data):
    from emporio_support_agent.catalog import check_availability

    result = check_availability(data.products[0])
    assert result.available is True
    assert result.requested_quantity == 1
    assert result.reason == "available"


@pytest.mark.parametrize("status,stock,quantity,available,reason", [
    ("active", 5, 1, True, "available"),
    ("active", 0, 1, False, "out_of_stock"),
    ("active", 2, 3, False, "insufficient_stock"),
    ("active", 2, 2, True, "available"),
    ("discontinued", 10, 1, False, "discontinued"),
    ("discontinued", 0, 1, False, "discontinued"),
    ("coming_soon", 10, 1, False, "coming_soon"),
    ("coming_soon", 0, 1, False, "coming_soon"),
    ("unexpected_status", 10, 1, False, "status_not_active"),
    ("ACTIVE", 10, 1, False, "status_not_active"),
    ("", 0, 1, False, "status_not_active"),
    ("active", -1, 1, False, "out_of_stock"),
])
def test_availability_checks_status_and_stock(data, status, stock, quantity, available, reason):
    from emporio_support_agent.catalog import AvailabilityResult, check_availability

    product = replace(data.products[0], status=status, stock_quantity=stock)
    result = check_availability(product, quantity)
    assert isinstance(result, AvailabilityResult)
    assert result.product_id == product.product_id
    assert result.requested_quantity == quantity
    assert result.available is available
    assert result.status == status
    assert result.stock_quantity == stock
    assert result.reason == reason


@pytest.mark.parametrize("quantity", [0, -1, True, "1", Decimal("1.5"), None])
def test_invalid_requested_quantities_fail(data, quantity):
    from emporio_support_agent.catalog import check_availability

    with pytest.raises(ValueError, match="positive integer"):
        check_availability(data.products[0], quantity)


def test_availability_is_immutable_and_does_not_decrement_stock(data):
    from emporio_support_agent.catalog import check_availability

    product = data.products[0]
    result = check_availability(product, 2)
    with pytest.raises(FrozenInstanceError):
        result.available = False
    assert product.stock_quantity == 5
    assert check_availability(product, 2) == result

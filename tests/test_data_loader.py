import csv
import shutil
import traceback
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from emporio_support_agent.data import (
    Category,
    Customer,
    DataLoadError,
    Order,
    OrderItem,
    Product,
    Promotion,
    StoreData,
    load_store_data,
)


FIXTURES = Path(__file__).parent / "fixtures" / "data"
DATASETS = ("categories", "products", "promotions", "customers", "orders", "order_items")


@pytest.fixture
def data_dir(tmp_path):
    return shutil.copytree(FIXTURES, tmp_path / "synthetic data á")


def read_csv(data_dir, dataset):
    with (data_dir / f"{dataset}.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def write_csv(data_dir, dataset, fields, rows):
    with (data_dir / f"{dataset}.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def replace_value(data_dir, dataset, field, value):
    fields, rows = read_csv(data_dir, dataset)
    rows[0][field] = value
    write_csv(data_dir, dataset, fields, rows)


def test_loads_all_six_typed_collections_and_preserves_source_values():
    data = load_store_data(FIXTURES)
    assert isinstance(data, StoreData)
    expected = (
        (data.categories, Category, 1), (data.products, Product, 2),
        (data.promotions, Promotion, 2), (data.customers, Customer, 2),
        (data.orders, Order, 2), (data.order_items, OrderItem, 2),
    )
    for records, model, count in expected:
        assert isinstance(records, tuple)
        assert len(records) == count
        assert all(isinstance(record, model) for record in records)
    product = data.products[0]
    assert product.product_id == 101 and type(product.product_id) is int
    assert product.category_id == 10 and type(product.category_id) is int
    assert product.stock_quantity == 0 and type(product.stock_quantity) is int
    assert product.name == "Demo Violão Árvore"
    assert product.description == "Demo description, with a comma"
    assert product.created_at == date(2025, 1, 10)
    assert data.customers[0].phone == "DEMO-PHONE-ONE"
    assert type(data.promotions[0].discount_percent) is int
    assert data.promotions[0].discount_percent == 10
    assert data.order_items[0] == OrderItem(order_id=401, quantity=2, product_id=101)


def test_money_is_decimal_without_rounding_or_losing_source_scale():
    data = load_store_data(FIXTURES)
    assert isinstance(data.products[0].price_brl, Decimal)
    assert data.products[0].price_brl.as_tuple() == Decimal("599.90").as_tuple()
    assert data.products[1].price_brl.as_tuple() == Decimal("799.9").as_tuple()
    assert isinstance(data.orders[1].total_brl, Decimal)
    assert data.orders[1].total_brl.as_tuple() == Decimal("123.45670").as_tuple()
    assert data.orders[0].total_brl == Decimal("1250.000")


def test_optional_fields_and_dates():
    data = load_store_data(FIXTURES)
    assert data.orders[1].tracking_code is None
    assert data.orders[1].estimated_delivery is None
    assert data.orders[1].notes is None
    assert data.orders[0].order_date == date(2025, 2, 1)
    assert data.orders[0].estimated_delivery == date(2025, 2, 11)
    assert data.orders[0].tracking_code == "DEMO-TRACK-ONE"
    assert data.orders[0].notes == "Demo order note"


def test_boolean_and_specs_values_are_preserved_without_business_decisions():
    data = load_store_data(FIXTURES)
    assert data.promotions[0].is_active is True
    assert data.promotions[1].is_active is False
    assert data.products[0].specs == {"strings": "nylon", "color": "Blue"}
    assert data.products[0].status == "active" and data.products[0].stock_quantity == 0
    assert data.products[1].status == "discontinued" and data.products[1].stock_quantity == 3
    assert data.products[1].name == "Demo Keyboard Brand A"
    assert data.products[1].description == "Demo Brand B with 88 keys"
    assert data.products[1].specs["keys"] == "61"


def test_loaded_records_and_collections_are_read_only():
    data = load_store_data(FIXTURES)
    with pytest.raises(FrozenInstanceError):
        data.products[0].stock_quantity = 999
    with pytest.raises(FrozenInstanceError):
        data.products = ()
    with pytest.raises(TypeError):
        data.products[0].specs["strings"] = "invented"


@pytest.mark.parametrize("value", ["true", "False", "2", ""])
def test_rejects_unknown_boolean_encoding(data_dir, value):
    replace_value(data_dir, "promotions", "is_active", value)
    with pytest.raises(DataLoadError, match=r"promotions.csv.*row 2.*is_active"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,field,value", [
    ("products", "product_id", "not-an-integer"),
    ("products", "stock_quantity", "1.5"),
    ("order_items", "quantity", "1_0"),
    ("promotions", "discount_percent", "10.5"),
    ("customers", "customer_id", ""),
])
def test_rejects_malformed_integers(data_dir, dataset, field, value):
    replace_value(data_dir, dataset, field, value)
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*row 2.*{field}"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,field", [("products", "price_brl"), ("orders", "total_brl")])
@pytest.mark.parametrize("value", ["invalid", "", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_rejects_invalid_or_nonfinite_money(data_dir, dataset, field, value):
    replace_value(data_dir, dataset, field, value)
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*row 2.*{field}"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,field", [
    ("products", "created_at"), ("orders", "order_date"), ("orders", "estimated_delivery"),
])
def test_rejects_invalid_dates(data_dir, dataset, field):
    replace_value(data_dir, dataset, field, "2025-02-30")
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*row 2.*{field}"):
        load_store_data(data_dir)


@pytest.mark.parametrize("value", ["{broken", "[]", "null", '{"keys":NaN}'])
def test_rejects_malformed_or_nonobject_specs(data_dir, value):
    replace_value(data_dir, "products", "specs", value)
    with pytest.raises(DataLoadError, match=r"products.csv.*row 2.*specs"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,field", [
    ("categories", "name"), ("products", "price_brl"),
    ("promotions", "is_active"), ("customers", "phone"),
    ("orders", "estimated_delivery"), ("order_items", "quantity"),
])
def test_rejects_missing_required_column(data_dir, dataset, field):
    fields, rows = read_csv(data_dir, dataset)
    fields.remove(field)
    for row in rows:
        del row[field]
    write_csv(data_dir, dataset, fields, rows)
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*{field}"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,key", [
    ("categories", "category_id"), ("products", "product_id"),
    ("promotions", "promotion_id"), ("customers", "customer_id"), ("orders", "order_id"),
])
def test_rejects_duplicate_primary_identifiers(data_dir, dataset, key):
    fields, rows = read_csv(data_dir, dataset)
    rows.append(rows[0].copy())
    write_csv(data_dir, dataset, fields, rows)
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*{key}.*duplicate"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset,field", [
    ("products", "category_id"), ("promotions", "product_id"),
    ("orders", "customer_id"), ("order_items", "order_id"), ("order_items", "product_id"),
])
def test_rejects_each_orphan_reference(data_dir, dataset, field):
    replace_value(data_dir, dataset, field, "99999")
    with pytest.raises(DataLoadError, match=rf"{dataset}.csv.*row 2.*{field}.*reference"):
        load_store_data(data_dir)


def test_repeated_order_item_pairs_and_shared_emails_are_allowed(data_dir):
    fields, rows = read_csv(data_dir, "order_items")
    rows.append(rows[0].copy())
    write_csv(data_dir, "order_items", fields, rows)
    replace_value(data_dir, "customers", "email", "demo2@example.test")
    data = load_store_data(data_dir)
    assert len(data.order_items) == 3
    assert data.order_items[0] == data.order_items[2]
    assert data.customers[0].email == data.customers[1].email


def test_accepts_reordered_columns_extra_columns_bom_and_multiline_text(data_dir):
    fields, rows = read_csv(data_dir, "products")
    fields = ["extra"] + list(reversed(fields))
    for row in rows:
        row["extra"] = "ignored demo field"
    rows[0]["description"] = 'Demo line one\nDemo line two, with "quotes"'
    write_csv(data_dir, "products", fields, rows)
    path = data_dir / "products.csv"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    data = load_store_data(data_dir)
    assert data.products[0].description == 'Demo line one\nDemo line two, with "quotes"'
    assert data.products[0].price_brl == Decimal("599.90")


def test_accepts_original_package_filenames_without_private_path_dependency(data_dir):
    for dataset in DATASETS:
        path = data_dir / f"{dataset}.csv"
        path.rename(data_dir / f"desafio_tecnico_ai_eng - {dataset}.csv")
    assert len(load_store_data(data_dir).products) == 2


def test_rejects_ambiguous_dataset_filenames(data_dir):
    shutil.copyfile(data_dir / "products.csv", data_dir / "desafio_tecnico_ai_eng - products.csv")
    with pytest.raises(DataLoadError, match=r"products.*ambiguous"):
        load_store_data(data_dir)


@pytest.mark.parametrize("dataset", DATASETS)
def test_rejects_missing_dataset(data_dir, dataset):
    (data_dir / f"{dataset}.csv").unlink()
    with pytest.raises(DataLoadError, match=rf"{dataset}.*missing"):
        load_store_data(data_dir)


@pytest.mark.parametrize("row", ["101,599.90", "101,599.90,x,10,x,0,active,{},2025-01-10,extra"])
def test_rejects_wrong_row_width(data_dir, row):
    path = data_dir / "products.csv"
    header = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(header + "\n" + row + "\n", encoding="utf-8")
    with pytest.raises(DataLoadError, match=r"products.csv.*row 2.*column"):
        load_store_data(data_dir)


def test_rejects_duplicate_header(data_dir):
    path = data_dir / "categories.csv"
    path.write_text("category_id,name,description,name\n10,Demo,Demo,Demo\n", encoding="utf-8")
    with pytest.raises(DataLoadError, match=r"categories.csv.*header.*duplicate"):
        load_store_data(data_dir)


@pytest.mark.parametrize("content", [b"", b"\xff", b'category_id,name,description\n10,"unterminated'])
def test_wraps_missing_header_encoding_and_csv_syntax_errors(data_dir, content):
    (data_dir / "categories.csv").write_bytes(content)
    with pytest.raises(DataLoadError, match=r"categories.csv"):
        load_store_data(data_dir)


def test_wraps_file_read_errors(data_dir):
    path = data_dir / "categories.csv"
    path.unlink()
    path.mkdir()
    with pytest.raises(DataLoadError, match=r"categories.csv.*read"):
        load_store_data(data_dir)


def test_empty_tables_with_valid_headers_are_not_rejected_by_fixed_source_counts(data_dir):
    for dataset in DATASETS:
        fields, _ = read_csv(data_dir, dataset)
        write_csv(data_dir, dataset, fields, [])
    data = load_store_data(data_dir)
    assert data.products == () and data.orders == () and data.categories == ()


def test_parse_error_does_not_echo_customer_content(data_dir):
    private_value = "PRIVATE-DEMO-CUSTOMER-CONTENT"
    replace_value(data_dir, "customers", "customer_id", private_value)
    with pytest.raises(DataLoadError) as caught:
        load_store_data(data_dir)
    rendered = "".join(traceback.format_exception(caught.value))
    assert private_value not in rendered
    assert "customers.csv" in str(caught.value)
    assert "row 2" in str(caught.value)
    assert "customer_id" in str(caught.value)

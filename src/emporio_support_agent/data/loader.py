"""Load six CSV tables and validate their schema, types, keys and references."""

import csv
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

from .models import Category, Customer, Order, OrderItem, Product, Promotion, StoreData


class DataLoadError(ValueError):
    """A dataset could not be read, parsed or structurally validated."""


def _integer(value: str) -> int:
    if not re.fullmatch(r"[+-]?[0-9]+", value):
        raise ValueError("expected an integer")
    try:
        return int(value)
    except ValueError:
        raise ValueError("integer exceeds the supported parsing limit") from None


def _money(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("expected a finite decimal amount") from None
    if not result.is_finite():
        raise ValueError("expected a finite decimal amount")
    return result


def _date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError:
        raise ValueError("expected a date in YYYY-MM-DD format") from None
    if result.isoformat() != value:
        raise ValueError("expected a date in YYYY-MM-DD format")
    return result


def _optional_text(value: str) -> str | None:
    return value if value.strip() else None


def _optional_date(value: str) -> date | None:
    return _date(value) if value.strip() else None


def _boolean(value: str) -> bool:
    if value not in ("0", "1"):
        raise ValueError("expected 0 or 1")
    return value == "1"


def _invalid_json_constant(value: str):
    raise ValueError("nonstandard JSON constant")


def _specs(value: str):
    try:
        result = json.loads(value, parse_constant=_invalid_json_constant)
    except (ValueError, RecursionError):
        raise ValueError("expected a valid JSON object") from None
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object")
    return MappingProxyType(result)


# Each key is required, including columns whose values may be blank.
# Extra columns are accepted but are not part of the typed source records.
_SCHEMAS = {
    "categories": {"category_id": _integer, "name": str, "description": str},
    "products": {
        "product_id": _integer, "price_brl": _money, "name": str,
        "category_id": _integer, "description": str, "stock_quantity": _integer,
        "status": str, "specs": _specs, "created_at": _date,
    },
    "promotions": {
        "promotion_id": _integer, "product_id": _integer,
        "discount_percent": _integer, "description": str, "is_active": _boolean,
    },
    "customers": {
        "customer_id": _integer, "name": str, "phone": str, "email": str, "city": str,
    },
    "orders": {
        "order_id": _integer, "customer_id": _integer, "order_date": _date,
        "status": str, "total_brl": _money, "payment_method": str,
        "tracking_code": _optional_text, "estimated_delivery": _optional_date,
        "notes": _optional_text,
    },
    "order_items": {"order_id": _integer, "quantity": _integer, "product_id": _integer},
}

_PRIMARY_KEYS = {
    "categories": "category_id", "products": "product_id", "promotions": "promotion_id",
    "customers": "customer_id", "orders": "order_id",
}

T = TypeVar("T")


def _resolve_path(data_dir: Path, dataset: str) -> Path:
    candidates = (data_dir / f"{dataset}.csv", data_dir / f"desafio_tecnico_ai_eng - {dataset}.csv")
    try:
        matches = [path for path in candidates if path.exists()]
    except OSError:
        raise DataLoadError(f"{dataset}.csv: could not inspect dataset files") from None
    if not matches:
        raise DataLoadError(f"{dataset}.csv: missing dataset file")
    if len(matches) != 1:
        raise DataLoadError(f"{dataset}.csv: ambiguous dataset filenames")
    return matches[0]


def _read_dataset(path: Path, dataset: str, record_type: type[T]) -> tuple[T, ...]:
    schema = _SCHEMAS[dataset]
    records = []
    seen = set()
    row_number = 1
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, None)
            if not header:
                raise DataLoadError(f"{path.name}: row 1: missing header")
            if len(header) != len(set(header)):
                raise DataLoadError(f"{path.name}: row 1: header has duplicate columns")
            missing = schema.keys() - set(header)
            if missing:
                raise DataLoadError(f"{path.name}: row 1: missing required columns: {', '.join(sorted(missing))}")
            # Row numbers count CSV records, with the header as row 1.
            # Quoted multiline fields remain one record.
            for row_number, cells in enumerate(reader, start=2):
                if len(cells) != len(header):
                    raise DataLoadError(f"{path.name}: row {row_number}: column count does not match header")
                raw = dict(zip(header, cells))
                values = {}
                for field, parse in schema.items():
                    try:
                        values[field] = parse(raw[field])
                    except ValueError as error:
                        raise DataLoadError(f"{path.name}: row {row_number}, field {field}: {error}") from None
                key = _PRIMARY_KEYS.get(dataset)
                if key:
                    if values[key] in seen:
                        raise DataLoadError(f"{path.name}: row {row_number}, field {key}: duplicate identifier")
                    seen.add(values[key])
                records.append(record_type(**values))
    except (OSError, UnicodeError):
        raise DataLoadError(f"{path.name}: row {row_number}: could not read UTF-8 CSV") from None
    except csv.Error:
        raise DataLoadError(f"{path.name}: near row {row_number + 1}: malformed CSV") from None
    return tuple(records)


def _validate_references(data: StoreData, paths: dict[str, Path]) -> None:
    category_ids = {record.category_id for record in data.categories}
    product_ids = {record.product_id for record in data.products}
    customer_ids = {record.customer_id for record in data.customers}
    order_ids = {record.order_id for record in data.orders}
    checks = (
        ("products", data.products, "category_id", category_ids),
        ("promotions", data.promotions, "product_id", product_ids),
        ("orders", data.orders, "customer_id", customer_ids),
        ("order_items", data.order_items, "order_id", order_ids),
        ("order_items", data.order_items, "product_id", product_ids),
    )
    for dataset, records, field, known_ids in checks:
        for row_number, record in enumerate(records, start=2):
            if getattr(record, field) not in known_ids:
                raise DataLoadError(f"{paths[dataset].name}: row {row_number}, field {field}: unknown reference")


def load_store_data(data_dir: Path) -> StoreData:
    """Load six CSVs in source order; raise DataLoadError on structural failure.

    Accept <dataset>.csv or the original package's prefixed filenames.
    Never choose silently when both exist. No fixed row counts or business
    rules are enforced. Error messages omit record values and customer data.
    """
    paths = {dataset: _resolve_path(data_dir, dataset) for dataset in _SCHEMAS}
    data = StoreData(
        categories=_read_dataset(paths["categories"], "categories", Category),
        products=_read_dataset(paths["products"], "products", Product),
        promotions=_read_dataset(paths["promotions"], "promotions", Promotion),
        customers=_read_dataset(paths["customers"], "customers", Customer),
        orders=_read_dataset(paths["orders"], "orders", Order),
        order_items=_read_dataset(paths["order_items"], "order_items", OrderItem),
    )
    _validate_references(data, paths)
    return data

"""Exact catalog lookups, source-order filtering and stock availability."""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from .data import Category, Product, StoreData


@dataclass(frozen=True)
class AvailabilityResult:
    product_id: int
    requested_quantity: int
    available: bool
    status: str
    stock_quantity: int
    reason: str


def get_category_by_id(data: StoreData, category_id: int) -> Category | None:
    """Return the original category, or None when the ID is unknown."""
    return next((category for category in data.categories if category.category_id == category_id), None)


def get_product_by_id(data: StoreData, product_id: int) -> Product | None:
    """Return the original product without reconciling its source fields."""
    return next((product for product in data.products if product.product_id == product_id), None)


def filter_products(
    data: StoreData,
    *,
    category_id: int | None = None,
    status: str | None = None,
) -> tuple[Product, ...]:
    """Apply exact optional filters, preserving source order and records."""
    return tuple(
        product for product in data.products
        if (category_id is None or product.category_id == category_id)
        and (status is None or product.status == status)
    )


def check_availability(product: Product, quantity: int = 1) -> AvailabilityResult:
    """Check status and sufficient stock without reserving or mutating it.

    Nonpositive stock is conservatively out of stock; an unknown status is
    never treated as active. Quantity must be a positive integer, not bool.
    """
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    if product.status != "active":
        reason = {
            "discontinued": "discontinued",
            "coming_soon": "coming_soon",
        }.get(product.status, "status_not_active")
    elif product.stock_quantity <= 0:
        reason = "out_of_stock"
    elif product.stock_quantity < quantity:
        reason = "insufficient_stock"
    else:
        reason = "available"
    return AvailabilityResult(
        product_id=product.product_id,
        requested_quantity=quantity,
        available=reason == "available",
        status=product.status,
        stock_quantity=product.stock_quantity,
        reason=reason,
    )


def _lexical_terms(text: str) -> set[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return set(re.findall(r"[^\W_]+", text))


def _spec_text(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _spec_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _spec_text(item)


def search_catalog_products(
    data: StoreData,
    *,
    query: str | None = None,
    category: str | None = None,
) -> tuple[Product, ...]:
    """Require all normalized query terms somewhere in the source fields.

    Category is an all-term lexical filter on the category name. Rank by the
    first matching field: name, category, description, then textual specs.
    Within that field prefer more distinct matches, then source order.
    No stemming, aliases, field reconciliation, pricing or stock decisions.
    """
    terms = _lexical_terms(query) if query is not None else set()
    category_terms = _lexical_terms(category) if category is not None else set()
    if (query is not None and not terms) or (category is not None and not category_terms):
        return ()
    categories = {item.category_id: item.name for item in data.categories}
    ranked = []
    for position, product in enumerate(data.products):
        category_words = _lexical_terms(categories.get(product.category_id, ""))
        if not category_terms <= category_words:
            continue
        words = (
            _lexical_terms(product.name), category_words,
            _lexical_terms(product.description), _lexical_terms(" ".join(_spec_text(product.specs))),
        )
        if not terms <= set().union(*words):
            continue
        hits = tuple(len(terms & field) for field in words)
        first = next((index for index, count in enumerate(hits) if count), 0)
        ranked.append((first, -hits[first], position, product))
    ranked.sort(key=lambda item: item[:3])
    return tuple(product for _, _, _, product in ranked)

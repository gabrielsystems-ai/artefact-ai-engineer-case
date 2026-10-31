"""Exact catalog lookups, source-order filtering and stock availability."""

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

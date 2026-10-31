"""Owner-scoped order views using application-supplied demo identity.

Ownership checks are not authentication. The application must supply the
customer ID from its session, never from a model-controlled override.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .data import Order, StoreData


@dataclass(frozen=True)
class OrderItemView:
    product_id: int
    product_name: str
    quantity: int


@dataclass(frozen=True)
class OrderView:
    order_id: int
    order_date: date
    status: str
    historical_total_brl: Decimal
    payment_method: str
    tracking_code: str | None
    estimated_delivery: date | None
    notes: str | None
    items: tuple[OrderItemView, ...]


def _validate_id(value: int, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


def _build_view(data: StoreData, order: Order) -> OrderView:
    """Build only after ownership is checked; item references are loader-validated."""
    product_names = {product.product_id: product.name for product in data.products}
    items = tuple(
        OrderItemView(
            product_id=item.product_id,
            product_name=product_names[item.product_id],
            quantity=item.quantity,
        )
        for item in data.order_items if item.order_id == order.order_id
    )
    return OrderView(
        order_id=order.order_id,
        order_date=order.order_date,
        status=order.status,
        historical_total_brl=order.total_brl,
        payment_method=order.payment_method,
        tracking_code=order.tracking_code,
        estimated_delivery=order.estimated_delivery,
        notes=order.notes,
        items=items,
    )


def get_order_for_customer(
    data: StoreData,
    *,
    customer_id: int,
    order_id: int,
) -> OrderView | None:
    """Return an owned order; missing and inaccessible orders both return None."""
    _validate_id(customer_id, "customer_id")
    _validate_id(order_id, "order_id")
    order = next(
        (order for order in data.orders
         if order.order_id == order_id and order.customer_id == customer_id),
        None,
    )
    return _build_view(data, order) if order is not None else None


def list_orders_for_customer(
    data: StoreData,
    *,
    customer_id: int,
) -> tuple[OrderView, ...]:
    """Return only owned orders in source order, including cancelled orders."""
    _validate_id(customer_id, "customer_id")
    return tuple(
        _build_view(data, order) for order in data.orders
        if order.customer_id == customer_id
    )

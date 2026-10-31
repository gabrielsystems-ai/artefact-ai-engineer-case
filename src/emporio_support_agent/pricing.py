"""Deterministic unit prices; a quote does not imply stock availability."""

from dataclasses import dataclass
from decimal import Context, Decimal, DecimalException, ROUND_HALF_UP, localcontext

from .data import Product, Promotion


class PricingConflictError(ValueError):
    """Promotion data does not define an unambiguous valid current price."""


@dataclass(frozen=True)
class PriceQuote:
    product_id: int
    list_price: Decimal
    final_price: Decimal
    discount_percent: int | None
    promotion_description: str | None
    promotion_applied: bool
    pix_discount_applied: bool


def get_active_promotion(
    product: Product,
    promotions: tuple[Promotion, ...],
) -> Promotion | None:
    """Select by product ID and activity flag only; never resolve conflicts."""
    active = tuple(
        promotion for promotion in promotions
        if promotion.product_id == product.product_id and promotion.is_active
    )
    if len(active) > 1:
        raise PricingConflictError(f"Product {product.product_id}: multiple active promotions")
    return active[0] if active else None


def quote_product_price(
    product: Product,
    promotions: tuple[Promotion, ...],
    *,
    payment_method: str | None = None,
) -> PriceQuote:
    """Quote a unit price with one promotion, or PIX 5%, or no discount.

    Preserve list_price exactly. Round final_price once to BRL cents using
    ROUND_HALF_UP. Payment matching only strips whitespace and ignores case.
    Invalid source amounts/discounts fail explicitly; they are not corrected.
    """
    price = product.price_brl
    if not isinstance(price, Decimal) or not price.is_finite() or price < 0:
        raise ValueError(f"Product {product.product_id}: invalid list price")
    promotion = get_active_promotion(product, promotions)
    if promotion is not None:
        discount = promotion.discount_percent
        if type(discount) is not int or not 0 <= discount <= 100:
            raise PricingConflictError(f"Product {product.product_id}: invalid active promotion discount")
        pix_applied = False
    else:
        pix_applied = payment_method is not None and payment_method.strip().casefold() == "pix"
        discount = 5 if pix_applied else None

    # Isolate caller precision/traps and allow enough digits for exact
    # percentage arithmetic before the single final cent rounding.
    precision = max(28, len(price.as_tuple().digits) + 4, price.adjusted() + 4)
    try:
        with localcontext(Context(prec=precision)):
            final_price = (price * Decimal(100 - (discount or 0)) / Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP,
            )
    except DecimalException:
        raise ValueError(f"Product {product.product_id}: list price cannot be quoted in BRL cents") from None

    return PriceQuote(
        product_id=product.product_id,
        list_price=price,
        final_price=final_price,
        discount_percent=discount,
        promotion_description=promotion.description if promotion is not None else None,
        promotion_applied=promotion is not None,
        pix_discount_applied=pix_applied,
    )

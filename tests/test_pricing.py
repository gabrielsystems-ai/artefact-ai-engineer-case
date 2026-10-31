from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from emporio_support_agent.data import Promotion, load_store_data


@pytest.fixture
def product():
    source = load_store_data(Path(__file__).parent / "fixtures" / "data")
    return replace(source.products[0], price_brl=Decimal("1000.00"), stock_quantity=5)


@pytest.fixture
def promotion(product):
    return Promotion(701, product.product_id, 20, "Demo promotion", True)


@pytest.mark.parametrize("payment", [None, "credit", "debit", "boleto", "", "pix+card"])
def test_table_price_without_promotion_or_pix(product, payment):
    from emporio_support_agent.pricing import PriceQuote, quote_product_price

    quote = quote_product_price(product, (), payment_method=payment)
    assert isinstance(quote, PriceQuote)
    assert quote.product_id == product.product_id
    assert quote.list_price == Decimal("1000.00")
    assert quote.final_price.as_tuple() == Decimal("1000.00").as_tuple()
    assert quote.discount_percent is None
    assert quote.promotion_description is None
    assert quote.promotion_applied is False
    assert quote.pix_discount_applied is False


@pytest.mark.parametrize("payment", ["pix", "PIX", " Pix "])
def test_pix_discount_is_exactly_five_percent(product, payment):
    from emporio_support_agent.pricing import quote_product_price

    quote = quote_product_price(product, (), payment_method=payment)
    assert isinstance(quote.final_price, Decimal)
    assert quote.final_price == Decimal("950.00")
    assert quote.discount_percent == 5
    assert quote.promotion_applied is False
    assert quote.pix_discount_applied is True
    assert quote.promotion_description is None


@pytest.mark.parametrize("payment", [None, "credit", "pix", " PIX "])
def test_active_promotion_applies_without_stacking_pix(product, promotion, payment):
    from emporio_support_agent.pricing import quote_product_price

    quote = quote_product_price(product, (promotion,), payment_method=payment)
    assert quote.list_price == Decimal("1000.00")
    assert quote.final_price == Decimal("800.00")
    assert quote.discount_percent == 20
    assert quote.promotion_description == "Demo promotion"
    assert quote.promotion_applied is True
    assert quote.pix_discount_applied is False


@pytest.mark.parametrize("discount,expected", [(0, "1000.00"), (100, "0.00")])
def test_active_discount_boundaries_still_prevent_pix_stacking(product, promotion, discount, expected):
    from emporio_support_agent.pricing import quote_product_price

    quote = quote_product_price(product, (replace(promotion, discount_percent=discount),), payment_method="pix")
    assert quote.final_price == Decimal(expected)
    assert quote.promotion_applied is True
    assert quote.pix_discount_applied is False


def test_inactive_campaign_names_never_activate_discounts(product, promotion):
    from emporio_support_agent.pricing import get_active_promotion, quote_product_price

    inactive = (
        replace(promotion, is_active=False, discount_percent=90, description="Black Friday"),
        replace(promotion, promotion_id=702, is_active=False, discount_percent=95),
    )
    assert get_active_promotion(product, inactive) is None
    assert quote_product_price(product, inactive).final_price == Decimal("1000.00")
    assert quote_product_price(product, inactive, payment_method="pix").final_price == Decimal("950.00")


def test_only_matching_product_and_active_flag_select_promotion(product, promotion):
    from emporio_support_agent.pricing import get_active_promotion, quote_product_price

    promotions = (
        replace(promotion, promotion_id=702, is_active=False, discount_percent=99),
        replace(promotion, promotion_id=703, product_id=999, discount_percent=80),
        promotion,
        replace(promotion, promotion_id=704, product_id=999, discount_percent=90),
    )
    assert get_active_promotion(product, promotions) is promotion
    assert quote_product_price(product, promotions).final_price == Decimal("800.00")
    assert get_active_promotion(product, promotions[:2]) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_active_promotions_raise_a_deterministic_conflict(product, promotion, reverse):
    from emporio_support_agent.pricing import PricingConflictError, get_active_promotion, quote_product_price

    promotions = (promotion, replace(promotion, promotion_id=702, discount_percent=30))
    if reverse:
        promotions = tuple(reversed(promotions))
    for operation in (
        lambda: get_active_promotion(product, promotions),
        lambda: quote_product_price(product, promotions, payment_method="pix"),
    ):
        with pytest.raises(PricingConflictError, match=rf"{product.product_id}.*multiple active promotions"):
            operation()


@pytest.mark.parametrize("price,discount,payment,expected", [
    ("0.10", None, "pix", "0.10"),
    ("0.05", 10, None, "0.05"),
    ("10.005", None, None, "10.01"),
    ("1000.01", 20, "pix", "800.01"),
])
def test_cent_rounding_is_half_up_and_source_price_is_preserved(product, promotion, price, discount, payment, expected):
    from emporio_support_agent.pricing import quote_product_price

    product = replace(product, price_brl=Decimal(price))
    promotions = () if discount is None else (replace(promotion, discount_percent=discount),)
    quote = quote_product_price(product, promotions, payment_method=payment)
    assert quote.final_price.as_tuple() == Decimal(expected).as_tuple()
    assert quote.list_price.as_tuple() == Decimal(price).as_tuple()
    assert product.price_brl.as_tuple() == Decimal(price).as_tuple()


def test_pricing_is_independent_of_callers_decimal_precision(product, promotion):
    from emporio_support_agent.pricing import quote_product_price

    product = replace(product, price_brl=Decimal("1000.01"))
    with localcontext() as context:
        context.prec = 3
        quote = quote_product_price(product, (promotion,))
        assert context.prec == 3
    assert quote.final_price == Decimal("800.01")


@pytest.mark.parametrize("status,stock", [("active", 0), ("discontinued", 5), ("coming_soon", 5)])
def test_price_does_not_imply_availability(product, promotion, status, stock):
    from emporio_support_agent.catalog import check_availability
    from emporio_support_agent.pricing import quote_product_price

    product = replace(product, status=status, stock_quantity=stock)
    assert quote_product_price(product, (promotion,), payment_method="pix").final_price == Decimal("800.00")
    assert check_availability(product).available is False


def test_quotes_are_frozen_and_source_records_are_unchanged(product, promotion):
    from emporio_support_agent.pricing import quote_product_price

    before_product = replace(product)
    before_promotion = replace(promotion)
    quote = quote_product_price(product, (promotion,), payment_method="pix")
    with pytest.raises(FrozenInstanceError):
        quote.final_price = Decimal("0")
    assert product == before_product
    assert promotion == before_promotion


@pytest.mark.parametrize("discount", [-1, 101, True, Decimal("10.5")])
def test_invalid_active_discount_cannot_produce_a_misleading_quote(product, promotion, discount):
    from emporio_support_agent.pricing import PricingConflictError, quote_product_price

    with pytest.raises(PricingConflictError, match=rf"{product.product_id}.*discount"):
        quote_product_price(product, (replace(promotion, discount_percent=discount),))


@pytest.mark.parametrize("price", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity")])
def test_invalid_source_price_fails_explicitly(product, price):
    from emporio_support_agent.pricing import quote_product_price

    with pytest.raises(ValueError, match=rf"{product.product_id}.*list price"):
        quote_product_price(replace(product, price_brl=price), ())

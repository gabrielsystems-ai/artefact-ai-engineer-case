import json
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from emporio_support_agent.data import Category, OrderItem, Promotion, load_store_data
from emporio_support_agent.policies import PolicyCorpus, PolicyPage, PolicySection, PolicySource


NAMES = ("search_products", "get_product_details", "get_order_status", "list_my_orders", "search_store_policies")


def sample_context(customer_id=301):
    from emporio_support_agent.tools import ToolContext

    source = load_store_data(Path(__file__).parent / "fixtures" / "data")
    base = source.products[0]
    products = (
        replace(base, product_id=101, name="Demo Violão Alpha", description="Demo sound", stock_quantity=5, price_brl=Decimal("1000.00")),
        replace(base, product_id=102, name="Demo Beta", description="Alpha in the description", stock_quantity=2, price_brl=Decimal("1000.00")),
        replace(base, product_id=103, name="Demo Future", status="coming_soon", stock_quantity=8),
        replace(base, product_id=104, name="Demo Retired", status="discontinued", stock_quantity=8),
        replace(base, product_id=105, name="Demo Empty", stock_quantity=0),
        replace(base, product_id=106, name="Demo Gamma", category_id=20, stock_quantity=5, description="Conflicting brand with 88 keys", specs=MappingProxyType({"keys": "61", "detail": {"label": "Alpha"}})),
    )
    data = replace(
        source,
        categories=(Category(10, "Violões", "Demo category"), Category(20, "Alpha Keyboards", "Demo category")),
        products=products,
        promotions=(Promotion(701, 101, 20, "Demo active promotion", True), Promotion(702, 102, 99, "Demo inactive campaign", False)),
        orders=(replace(source.orders[0], total_brl=Decimal("900.000")), source.orders[1], replace(source.orders[0], order_id=403, status="cancelled", notes="Demo cancellation")),
        order_items=(OrderItem(401, 2, 101), OrderItem(402, 1, 102), OrderItem(403, 1, 106)),
    )
    policies = PolicyCorpus(
        PolicySource("demo-policy.pdf", "a" * 64, "9.3"), (PolicyPage(1, "Demo policy"),),
        (PolicySection("1", "Contato WhatsApp", "Demo contact channel A, condition one and condition two.", 1, 1),
         PolicySection("2", "Contato WhatsApp", "Demo contact channel B; retain both statements.", 2, 3)),
    )
    return ToolContext(data=data, policies=policies, customer_id=customer_id)


def call(name, arguments, context=None):
    from emporio_support_agent.tools import execute_tool

    return execute_tool(sample_context() if context is None else context, name, arguments)


def assert_json_native(value):
    assert type(value) in (dict, list, str, int, float, bool, type(None))
    if isinstance(value, dict):
        assert all(isinstance(key, str) for key in value)
        for item in value.values():
            assert_json_native(item)
    elif isinstance(value, list):
        for item in value:
            assert_json_native(item)
    json.dumps(value, allow_nan=False)


def test_registry_has_exactly_five_strict_serializable_schemas():
    from emporio_support_agent.tools import get_tool_definitions

    definitions = get_tool_definitions()
    assert isinstance(definitions, tuple)
    assert tuple(tool.name for tool in definitions) == NAMES
    assert len({tool.name for tool in definitions}) == 5
    for tool in definitions:
        schema = tool.parameters
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert isinstance(schema["required"], list)
        assert tool.description.strip()
        json.dumps(schema, allow_nan=False)
    schemas = {tool.name: tool.parameters for tool in definitions}
    assert set(schemas["get_order_status"]["properties"]) == {"order_id"}
    assert schemas["get_order_status"]["required"] == ["order_id"]
    assert schemas["list_my_orders"]["properties"] == {}
    assert schemas["list_my_orders"]["required"] == []
    assert all("customer_id" not in schema["properties"] for schema in schemas.values())
    assert schemas["get_product_details"]["required"] == ["product_id"]
    assert schemas["search_store_policies"]["required"] == ["query"]
    assert schemas["search_products"]["properties"]["limit"]["maximum"] == 10
    assert schemas["search_store_policies"]["properties"]["limit"]["maximum"] == 5


def test_context_and_definitions_cannot_mutate_the_registry():
    from emporio_support_agent.tools import get_tool_definitions

    context = sample_context()
    with pytest.raises(FrozenInstanceError):
        context.customer_id = 302
    definition = get_tool_definitions()[0]
    with pytest.raises(FrozenInstanceError):
        definition.name = "other"
    schema_copy = definition.parameters
    schema_copy["properties"]["customer_id"] = {"type": "integer"}
    schema_copy["additionalProperties"] = True
    assert "customer_id" not in definition.parameters["properties"]
    assert definition.parameters["additionalProperties"] is False


@pytest.mark.parametrize("query", ["VIOLAO", "violão", "Violão!!!"])
def test_product_name_search_is_case_accent_and_punctuation_insensitive(query):
    result = call("search_products", {"query": query})
    assert result["ok"] is True
    assert [p["product_id"] for p in result["data"]["products"]] == [101]


def test_product_ranking_prefers_name_category_description_then_specs():
    context = sample_context()
    extra = replace(context.data.products[0], product_id=107, name="Demo Delta", category_id=10, description="Demo", specs=MappingProxyType({"label": "Alpha"}))
    context = replace(context, data=replace(context.data, products=context.data.products + (extra,)))
    result = call("search_products", {"query": "alpha", "limit": 10}, context)
    assert [p["product_id"] for p in result["data"]["products"]] == [101, 106, 102, 107]
    result = call("search_products", {"category": "VIOLÕES", "limit": 10}, context)
    assert [p["product_id"] for p in result["data"]["products"]] == [101, 102, 103, 104, 105, 107]
    assert call("search_products", {"category": "missing"}, context)["data"]["products"] == []


def test_search_requires_all_query_terms_somewhere_and_preserves_source_ties():
    context = sample_context()
    result = call("search_products", {"query": "demo", "limit": 2}, context)
    assert [p["product_id"] for p in result["data"]["products"]] == [101, 102]
    assert result["data"]["total_matches"] == 6
    assert call("search_products", {"query": "alpha impossible"}, context)["data"]["products"] == []
    assert call("search_products", {"query": "!!!"}, context)["data"]["products"] == []


@pytest.mark.parametrize("payment,budget,expected", [(None, "850.00", [101]), ("pix", "950.00", [101, 102]), ("pix", "790.00", [])])
def test_budget_uses_current_unit_price_and_never_stacks_pix(payment, budget, expected):
    arguments = {"category": "violoes", "query": "alpha" if expected == [101] else "demo", "max_price_brl": budget, "available_only": True, "limit": 10}
    if payment is not None:
        arguments["payment_method"] = payment
    context = sample_context()
    context = replace(context, data=replace(context.data, products=context.data.products[:2]))
    result = call("search_products", arguments, context)
    assert [p["product_id"] for p in result["data"]["products"]] == expected
    if 101 in expected:
        promoted = result["data"]["products"][0]
        assert promoted["final_price_brl"] == "800.00"
        assert promoted["promotion_discount_percent"] == 20
        assert promoted["pix_discount_applied"] is False


def test_available_only_uses_status_and_requested_quantity():
    result = call("search_products", {"available_only": True, "quantity": 3, "limit": 10})
    assert [p["product_id"] for p in result["data"]["products"]] == [101, 106]
    assert all(p["available"] and p["requested_quantity"] == 3 for p in result["data"]["products"])
    unfiltered = call("search_products", {"limit": 10})
    assert unfiltered["data"]["total_matches"] == 6
    assert "description" not in unfiltered["data"]["products"][0]
    assert "specs" not in unfiltered["data"]["products"][0]


def test_details_preserve_conflicting_fields_and_serialize_nested_specs():
    result = call("get_product_details", {"product_id": 106})
    data = result["data"]
    assert data["name"] == "Demo Gamma"
    assert data["description"] == "Conflicting brand with 88 keys"
    assert data["specs"] == {"keys": "61", "detail": {"label": "Alpha"}}
    assert data["category"] == "Alpha Keyboards"
    assert data["available"] is True
    assert_json_native(result)
    assert call("get_product_details", {"product_id": 999})["error"]["code"] == "product_not_found"


def test_details_can_quote_an_unavailable_product_without_claiming_stock():
    data = call("get_product_details", {"product_id": 103, "payment_method": "pix"})["data"]
    assert data["available"] is False and data["availability_reason"] == "coming_soon"
    assert data["pix_discount_applied"] is True


@pytest.mark.parametrize("tool,args", [("search_products", {"query": "alpha", "max_price_brl": "1000"}), ("get_product_details", {"product_id": 101})])
def test_pricing_ambiguity_is_a_controlled_error(tool, args):
    context = sample_context()
    context = replace(context, data=replace(context.data, promotions=context.data.promotions + (Promotion(703, 101, 30, "Other active", True),)))
    result = call(tool, args, context)
    assert result["ok"] is False and result["error"]["code"] == "pricing_conflict"
    assert_json_native(result)


def test_authorized_order_has_exact_historical_total_iso_dates_and_safe_items():
    result = call("get_order_status", {"order_id": 401})
    data = result["data"]
    assert data["historical_total_brl"] == "900.000"
    assert data["order_date"] == "2025-02-01"
    assert data["estimated_delivery"] == "2025-02-11"
    assert data["items"] == [{"product_id": 101, "product_name": "Demo Violão Alpha", "quantity": 2}]
    assert not set(data).intersection({"customer_id", "name", "phone", "email", "city", "received_at", "actual_delivery"})
    assert_json_native(result)


def test_foreign_and_missing_order_errors_are_exactly_identical():
    foreign = call("get_order_status", {"order_id": 402})
    missing = call("get_order_status", {"order_id": 999})
    assert foreign == missing == {"ok": False, "error": {"code": "order_not_found", "message": "Order not found for the current customer."}}


@pytest.mark.parametrize("tool,args", [("get_order_status", {"order_id": 401}), ("list_my_orders", {})])
@pytest.mark.parametrize("identity", [None, 0, True, "301"])
def test_missing_or_invalid_application_identity_fails_closed(tool, args, identity):
    result = call(tool, args, sample_context(identity))
    assert result["error"]["code"] == "customer_context_required"


def test_listing_uses_context_only_and_does_not_expose_customer_values():
    context = sample_context()
    result = call("list_my_orders", {}, context)
    assert [o["order_id"] for o in result["data"]["orders"]] == [401, 403]
    serialized = json.dumps(result, ensure_ascii=False)
    for customer in context.data.customers:
        for value in (customer.name, customer.phone, customer.email, customer.city):
            assert value not in serialized
    assert '"customer_id"' not in serialized
    assert call("list_my_orders", {}, sample_context(999))["data"]["orders"] == []
    missing_fields = call("get_order_status", {"order_id": 402}, sample_context(302))["data"]
    assert missing_fields["tracking_code"] is None and missing_fields["estimated_delivery"] is None


def test_policy_tool_returns_full_sections_provenance_and_conflicting_sources():
    context = sample_context()
    result = call("search_store_policies", {"query": "WHATSAPP contato"}, context)
    matches = result["data"]["matches"]
    assert [s["section_id"] for s in matches] == ["1", "2"]
    assert matches[0]["text"] == context.policies.sections[0].text
    assert matches[1]["page_end"] == 3
    for match in matches:
        for value in ("9.3", "demo-policy.pdf", "a" * 64, "section=" + match["section_id"]):
            assert value in match["provenance"]
    assert call("search_store_policies", {"query": "unrelated waffles"}) == {"ok": True, "data": {"matches": []}}
    assert_json_native(result)


@pytest.mark.parametrize("tool,args", [
    ("get_product_details", {}), ("get_order_status", {}), ("search_store_policies", {}),
    ("get_order_status", {"order_id": 401, "customer_id": 302}),
    ("list_my_orders", {"customer_id": 302}), ("list_my_orders", {"email": "DO-NOT-ECHO"}),
    ("search_products", {"unexpected": "DO-NOT-ECHO"}),
    ("search_store_policies", {"query": "contact", "customer_id": 302}),
    ("get_product_details", {"product_id": 101, "phone": "DO-NOT-ECHO"}),
    ("search_products", {"available_only": "true"}),
    ("search_products", {"payment_method": "PIX"}), ("get_product_details", {"product_id": 101, "payment_method": "debit"}),
    ("search_products", {"query": "  "}), ("search_products", {"category": ""}),
    ("search_store_policies", {"query": "  "}), ("search_store_policies", {"query": 42}),
])
def test_invalid_arguments_and_identity_injection_are_rejected_safely(tool, args):
    result = call(tool, args)
    assert result["error"]["code"] == "invalid_arguments"
    assert "DO-NOT-ECHO" not in json.dumps(result)
    assert_json_native(result)


@pytest.mark.parametrize("value", [0, -1, True, 1.0, "1", None])
@pytest.mark.parametrize("tool,field,base", [
    ("get_product_details", "product_id", {}), ("get_product_details", "quantity", {"product_id": 101}),
    ("search_products", "quantity", {}), ("search_products", "limit", {}),
    ("get_order_status", "order_id", {}), ("search_store_policies", "limit", {"query": "contact"}),
])
def test_integer_inputs_never_coerce_types_or_invalid_ranges(value, tool, field, base):
    assert call(tool, {**base, field: value})["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("tool,args", [("search_products", {"limit": 11}), ("search_store_policies", {"query": "contact", "limit": 6})])
def test_limits_have_explicit_upper_bounds(tool, args):
    assert call(tool, args)["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "1e3", "1,000", "", "DO-NOT-ECHO", 1000, Decimal("1000"), True])
def test_budget_requires_a_nonnegative_plain_decimal_string(value):
    result = call("search_products", {"max_price_brl": value})
    assert result["error"]["code"] == "invalid_arguments"
    assert "DO-NOT-ECHO" not in json.dumps(result)


@pytest.mark.parametrize("arguments", [None, [], "{}", 42])
def test_arguments_must_be_an_object(arguments):
    assert call("list_my_orders", arguments)["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("tool", ["unknown", "__import__", "quote_product_price", "load_store_data", "__dict__"])
def test_unknown_tool_names_cannot_execute_arbitrary_functions(tool):
    assert call(tool, {})["error"]["code"] == "unknown_tool"


@pytest.mark.parametrize("tool,args", [
    ("search_products", {}), ("get_product_details", {"product_id": 101}),
    ("get_order_status", {"order_id": 401}), ("list_my_orders", {}),
    ("search_store_policies", {"query": "contact"}),
])
def test_each_success_is_json_native_and_money_is_never_float(tool, args):
    result = call(tool, args)
    assert result["ok"] is True
    assert_json_native(result)
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("_brl"):
                    assert isinstance(item, str)
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(result)

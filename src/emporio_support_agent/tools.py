"""Provider-independent schemas and adapters over preloaded domain data."""

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date
from decimal import Decimal

from .catalog import check_availability, get_category_by_id, get_product_by_id, search_catalog_products
from .data import StoreData
from .orders import get_order_for_customer, list_orders_for_customer
from .policies import PolicyCorpus, policy_section_provenance, search_policy_sections
from .pricing import PricingConflictError, quote_product_price


@dataclass(frozen=True)
class ToolContext:
    """Application-owned demo identity and data snapshot; not authentication."""

    data: StoreData
    policies: PolicyCorpus
    customer_id: int | None = None


@dataclass(frozen=True, init=False)
class ToolDefinition:
    """Immutable definition whose parameters property returns a JSON-safe copy."""

    name: str
    description: str
    _schema_json: str = field(repr=False)

    def __init__(self, name: str, description: str, parameters: Mapping[str, object]):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "_schema_json", json.dumps(dict(parameters), allow_nan=False))

    @property
    def parameters(self) -> dict[str, object]:
        return json.loads(self._schema_json)


class ToolArgumentError(ValueError):
    """Arguments do not satisfy an explicit public tool schema."""


def _object_schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


_TEXT = {"type": "string", "minLength": 1}
_ID = {"type": "integer", "minimum": 1}
_QUANTITY = {"type": "integer", "minimum": 1, "default": 1}
_PIX = {"type": "string", "enum": ["pix"]}
_DEFINITIONS = (
    ToolDefinition("search_products", "Find instruments using concise product/category keywords, budget or availability filters. Prices are per unit.", _object_schema({
        "query": _TEXT, "category": _TEXT,
        "max_price_brl": {"type": "string", "pattern": r"^[0-9]+(?:\.[0-9]+)?$", "description": "Maximum current unit price in BRL; nonnegative decimal string, without exponent or separators."},
        "available_only": {"type": "boolean", "default": False}, "quantity": _QUANTITY,
        "payment_method": _PIX, "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
    })),
    ToolDefinition("get_product_details", "Get a known product's original details, current unit price and availability. Source fields may disagree.", _object_schema({
        "product_id": _ID, "quantity": _QUANTITY, "payment_method": _PIX,
    }, ("product_id",))),
    ToolDefinition("get_order_status", "Get one order belonging to the current demo customer. Identity is supplied by the application.", _object_schema({
        "order_id": _ID,
    }, ("order_id",))),
    ToolDefinition("list_my_orders", "List the current demo customer's historical orders, including cancelled orders.", _object_schema({})),
    ToolDefinition("search_store_policies", "Retrieve complete store-policy sections for payments, shipping, returns, warranty, hours, contacts, promotions or privacy, with provenance.", _object_schema({
        "query": _TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
    }, ("query",))),
)
_DEFINITIONS_BY_NAME = {definition.name: definition for definition in _DEFINITIONS}


def get_tool_definitions() -> tuple[ToolDefinition, ...]:
    return _DEFINITIONS


def _validate_arguments(schema, arguments):
    if not isinstance(arguments, Mapping):
        raise ToolArgumentError("expected an argument object")
    properties = schema["properties"]
    if set(arguments) - properties.keys() or set(schema["required"]) - arguments.keys():
        raise ToolArgumentError("unexpected or missing arguments")
    validated = {}
    for name, rule in properties.items():
        if name not in arguments:
            if "default" in rule:
                validated[name] = rule["default"]
            continue
        value = arguments[name]
        kind = rule["type"]
        if kind == "integer":
            if type(value) is not int or value < rule["minimum"] or ("maximum" in rule and value > rule["maximum"]):
                raise ToolArgumentError("invalid integer argument")
        elif kind == "boolean":
            if type(value) is not bool:
                raise ToolArgumentError("invalid boolean argument")
        elif kind == "string":
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError("invalid text argument")
            if "pattern" in rule and not re.fullmatch(rule["pattern"], value):
                raise ToolArgumentError("invalid decimal string")
        if "enum" in rule and value not in rule["enum"]:
            raise ToolArgumentError("unsupported argument value")
        validated[name] = value
    return validated


def _json_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite monetary data")
        return format(value, "f")
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("nontext JSON object keys")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite JSON data")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unexpected non-JSON domain value")


def _error(code, message):
    return {"ok": False, "error": {"code": code, "message": message}}


def _success(data):
    return {"ok": True, "data": data}


def _product_payload(data, product, availability, quote, *, details=False):
    category = get_category_by_id(data, product.category_id)
    if category is None:
        raise ValueError("missing product category")
    payload = {
        "product_id": product.product_id, "name": product.name, "category": category.name,
        "status": product.status, "stock_quantity": product.stock_quantity,
        "requested_quantity": availability.requested_quantity,
        "available": availability.available, "availability_reason": availability.reason,
        "list_price_brl": quote.list_price, "final_price_brl": quote.final_price,
        "promotion_applied": quote.promotion_applied,
        "promotion_discount_percent": quote.discount_percent if quote.promotion_applied else None,
        "pix_discount_applied": quote.pix_discount_applied,
    }
    if details:
        payload.update(description=product.description, specs=product.specs, promotion_description=quote.promotion_description)
    return payload


def _search_products(context, arguments):
    products = search_catalog_products(context.data, query=arguments.get("query"), category=arguments.get("category"))
    budget = Decimal(arguments["max_price_brl"]) if "max_price_brl" in arguments else None
    matches = []
    for product in products:
        availability = check_availability(product, arguments["quantity"])
        if arguments["available_only"] and not availability.available:
            continue
        quote = quote_product_price(product, context.data.promotions, payment_method=arguments.get("payment_method"))
        if budget is not None and quote.final_price > budget:
            continue
        matches.append(_product_payload(context.data, product, availability, quote))
    return _success({"total_matches": len(matches), "products": matches[:arguments["limit"]]})


def _get_product_details(context, arguments):
    product = get_product_by_id(context.data, arguments["product_id"])
    if product is None:
        return _error("product_not_found", "Product not found.")
    availability = check_availability(product, arguments["quantity"])
    quote = quote_product_price(product, context.data.promotions, payment_method=arguments.get("payment_method"))
    return _success(_product_payload(context.data, product, availability, quote, details=True))


def _has_customer(context):
    return type(context.customer_id) is int and context.customer_id > 0


def _get_order_status(context, arguments):
    if not _has_customer(context):
        return _error("customer_context_required", "Valid customer context is required.")
    view = get_order_for_customer(context.data, customer_id=context.customer_id, order_id=arguments["order_id"])
    if view is None:
        return _error("order_not_found", "Order not found for the current customer.")
    return _success(view)


def _list_my_orders(context, arguments):
    if not _has_customer(context):
        return _error("customer_context_required", "Valid customer context is required.")
    return _success({"orders": list_orders_for_customer(context.data, customer_id=context.customer_id)})


def _search_store_policies(context, arguments):
    matches = search_policy_sections(context.policies, arguments["query"], limit=arguments["limit"])
    return _success({"matches": [
        {"section_id": item.section_id, "title": item.title, "text": item.text,
         "page_start": item.page_start, "page_end": item.page_end,
         "provenance": policy_section_provenance(context.policies, item)}
        for item in matches
    ]})


_HANDLERS = {
    "search_products": _search_products, "get_product_details": _get_product_details,
    "get_order_status": _get_order_status, "list_my_orders": _list_my_orders,
    "search_store_policies": _search_store_policies,
}


def execute_tool(
    context: ToolContext,
    tool_name: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Validate before dispatch; expected failures return safe JSON envelopes."""
    if not isinstance(tool_name, str) or tool_name not in _HANDLERS:
        return _error("unknown_tool", "Unknown tool.")
    try:
        validated = _validate_arguments(_DEFINITIONS_BY_NAME[tool_name].parameters, arguments)
        return _json_value(_HANDLERS[tool_name](context, validated))
    except ToolArgumentError:
        return _error("invalid_arguments", "Invalid arguments for this tool.")
    except PricingConflictError:
        return _error("pricing_conflict", "An unambiguous current product price is unavailable.")
    except ValueError:
        return _error("data_error", "The supplied data could not be processed.")

import json

import pytest

from emporio_support_agent.tools import get_tool_definitions


def test_converts_all_five_tools_without_mutating_internal_schemas():
    from emporio_support_agent.openai_adapter import build_openai_tools

    definitions = get_tool_definitions()
    before = [definition.parameters for definition in definitions]
    tools = build_openai_tools(definitions)
    assert [tool["name"] for tool in tools] == [
        "search_products", "get_product_details", "get_order_status",
        "list_my_orders", "search_store_policies",
    ]
    for definition, tool in zip(definitions, tools, strict=True):
        assert tool["type"] == "function"
        assert tool["description"] == definition.description
        assert tool["strict"] is True
        schema = tool["parameters"]
        assert schema["additionalProperties"] is False
        assert schema["required"] == list(schema["properties"])
        for name, original in definition.parameters["properties"].items():
            converted = schema["properties"][name]
            if name in definition.parameters["required"]:
                assert converted["type"] == original["type"]
            else:
                assert converted["type"] == [original["type"], "null"]
                if "enum" in original:
                    assert converted["enum"] == [*original["enum"], None]
            assert "default" not in converted  # Defaults remain an internal concern.
            for constraint in ("minimum", "maximum", "minLength", "pattern"):
                if constraint in original:
                    assert converted[constraint] == original[constraint]
    assert tools[3]["parameters"] == {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False,
    }
    json.dumps(tools, allow_nan=False)
    tools[0]["parameters"]["properties"]["payment_method"]["enum"].append("other")
    assert [definition.parameters for definition in definitions] == before


def test_cleanup_removes_only_known_optional_nulls_and_never_coerces_values():
    from emporio_support_agent.openai_adapter import clean_openai_tool_arguments

    definition = get_tool_definitions()[1]
    before = definition.parameters
    arguments = {"product_id": None, "quantity": None, "payment_method": "pix", "unknown": None}
    assert clean_openai_tool_arguments(definition, arguments) == {
        "product_id": None, "payment_method": "pix", "unknown": None,
    }
    assert arguments["quantity"] is None
    assert definition.parameters == before
    assert clean_openai_tool_arguments(definition, {"product_id": "101", "quantity": 2}) == {
        "product_id": "101", "quantity": 2,
    }


@pytest.mark.parametrize("raw,expected", [
    ('{}', {}), ('{"query":"violão", "limit":null}', {"query": "violão", "limit": None}),
    ('{"product_id":101,"quantity":2}', {"product_id": 101, "quantity": 2}),
])
def test_parse_function_call_json_objects(raw, expected):
    from emporio_support_agent.openai_adapter import parse_function_call_arguments

    assert parse_function_call_arguments(raw) == expected


@pytest.mark.parametrize("raw", [
    '', '{', 'DO-NOT-ECHO', '[]', '1', 'true', 'null', '"text"',
    '{"limit":NaN}', '{"limit":Infinity}', None,
])
def test_rejects_malformed_non_object_and_non_json_constants_safely(raw):
    from emporio_support_agent.openai_adapter import OpenAIAdapterError, parse_function_call_arguments

    with pytest.raises(OpenAIAdapterError) as caught:
        parse_function_call_arguments(raw)
    assert "DO-NOT-ECHO" not in str(caught.value)

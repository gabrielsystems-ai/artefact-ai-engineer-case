"""Responses strict-schema translation for the five internal project tools."""

import json
from collections.abc import Mapping

from .tools import ToolDefinition


class OpenAIAdapterError(ValueError):
    """Provider arguments cannot be interpreted safely as an internal object."""


def build_openai_tools(definitions: tuple[ToolDefinition, ...]) -> list[dict[str, object]]:
    """Adapt the current flat object schemas without changing internal defaults."""
    tools = []
    for definition in definitions:
        schema = definition.parameters  # Defensive copy owned by this conversion.
        for name, rule in schema["properties"].items():
            rule.pop("default", None)
            if name not in schema["required"]:
                rule["type"] = [rule["type"], "null"]
                if "enum" in rule:
                    rule["enum"].append(None)
        schema["required"] = list(schema["properties"])
        tools.append({
            "type": "function", "name": definition.name,
            "description": definition.description, "parameters": schema, "strict": True,
        })
    return tools


def clean_openai_tool_arguments(
    definition: ToolDefinition,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Omit only known, internally optional nulls; validation stays in tools.py."""
    schema = definition.parameters
    optional = schema["properties"].keys() - set(schema["required"])
    return {name: value for name, value in arguments.items() if value is not None or name not in optional}


def _reject_constant(value: str) -> None:
    raise ValueError("Non-JSON constant")


def parse_function_call_arguments(raw_arguments: str) -> dict[str, object]:
    """Require a JSON object and never echo model-controlled argument text."""
    if not isinstance(raw_arguments, str):
        raise OpenAIAdapterError("Function arguments must be a JSON object.")
    try:
        arguments = json.loads(raw_arguments, parse_constant=_reject_constant)
    except ValueError as exc:
        raise OpenAIAdapterError("Function arguments must be a valid JSON object.") from exc
    if not isinstance(arguments, dict):
        raise OpenAIAdapterError("Function arguments must be a JSON object.")
    return arguments

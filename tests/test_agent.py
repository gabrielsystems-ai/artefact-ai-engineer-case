import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from emporio_support_agent.data import load_store_data
from emporio_support_agent.policies import PolicyCorpus, PolicyPage, PolicySection, PolicySource
from emporio_support_agent.tools import ToolContext


def final(response_id="final", text="Hello!", *, status="completed"):
    return SimpleNamespace(id=response_id, status=status, output=[], output_text=text)


def function(name="get_product_details", arguments='{"product_id":101}', call_id="call-1"):
    return SimpleNamespace(type="function_call", name=name, arguments=arguments, call_id=call_id)


def pending(response_id="pending", *calls):
    return SimpleNamespace(id=response_id, status="completed", output=list(calls or (function(),)), output_text="")


class FakeResponses:
    def __init__(self, script):
        self.script = iter(script)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        response = next(self.script)
        if isinstance(response, Exception):
            raise response
        return response


def client(*script):
    return SimpleNamespace(responses=FakeResponses(script))


@pytest.fixture
def context():
    return ToolContext(
        data=load_store_data(Path(__file__).parent / "fixtures" / "data"),
        policies=PolicyCorpus(
            PolicySource("demo.pdf", "a" * 64, "1"), (PolicyPage(1, "Demo policy"),),
            (PolicySection("1", "Hours", "Saturday: 09:00-13:00.", 1, 1),),
        ),
        customer_id=301,
    )


def test_no_tool_reply_is_immutable_and_stores_final_id_for_next_turn(context):
    from emporio_support_agent.agent import SupportAgent

    fake = client(final("first", "Hi!"), final("second", "Welcome back!"))
    agent = SupportAgent(context=context, client=fake)
    assert fake.responses.requests == []  # Construction must not call the API.
    reply = agent.respond("Hello")
    assert (reply.text, reply.response_id, reply.tool_names, reply.tool_call_count) == ("Hi!", "first", (), 0)
    with pytest.raises(FrozenInstanceError):
        reply.text = "changed"
    agent.respond("Hi again")
    assert fake.responses.requests[0]["previous_response_id"] is None
    assert fake.responses.requests[1]["previous_response_id"] == "first"


def test_search_tool_cleanup_outputs_and_request_configuration_across_turns(context):
    from emporio_support_agent.agent import SYSTEM_INSTRUCTIONS, SupportAgent

    arguments = json.dumps({
        "query": "arvore", "category": None, "max_price_brl": None,
        "available_only": None, "quantity": None, "payment_method": None, "limit": None,
    })
    fake = client(pending("lookup", function("search_products", arguments, "search-call")), final("answer", "Found one."), final("later", "You're welcome."))
    agent = SupportAgent(context=context, client=fake)
    reply = agent.respond("Find an instrument")
    assert reply.text == "Found one."
    assert reply.tool_names == ("search_products",) and reply.tool_call_count == 1
    continuation = fake.responses.requests[1]
    assert continuation["previous_response_id"] == "lookup"
    output = continuation["input"][0]
    assert output["type"] == "function_call_output" and output["call_id"] == "search-call"
    result = json.loads(output["output"])
    assert result["ok"] is True
    assert result["data"]["total_matches"] == 1
    product = result["data"]["products"][0]
    assert product["product_id"] == 101 and product["requested_quantity"] == 1
    assert product["available"] is False
    agent.respond("Thanks")
    assert fake.responses.requests[2]["previous_response_id"] == "answer"
    for request in fake.responses.requests:
        assert request["instructions"] == SYSTEM_INSTRUCTIONS
        assert request["model"] == "gpt-6.1-terra"
        assert request["tool_choice"] == "auto"
        assert request["parallel_tool_calls"] is False
        assert request["store"] is True
        assert request["max_output_tokens"] > 0
        assert [tool["name"] for tool in request["tools"]] == [
            "search_products", "get_product_details", "get_order_status", "list_my_orders", "search_store_policies",
        ]
        assert all(tool["strict"] for tool in request["tools"])


@pytest.mark.parametrize("arguments,expected", [
    ('{"order_id":401}', "success"),
    ('{"order_id":401,"customer_id":302}', "invalid_arguments"),
    ('{"order_id":402}', "order_not_found"),
    ('{"order_id":999}', "order_not_found"),
])
def test_order_identity_is_application_owned_and_model_outputs_are_private(context, arguments, expected):
    from emporio_support_agent.agent import SupportAgent

    fake = client(pending("order", function("get_order_status", arguments)), final(text="Order response"))
    SupportAgent(context=context, client=fake).respond("Check my order")
    result = json.loads(fake.responses.requests[1]["input"][0]["output"])
    if expected == "success":
        assert result["data"]["historical_total_brl"] == "1250.000"
        assert result["data"]["status"] == "shipped"
    else:
        assert result["error"]["code"] == expected
    serialized = json.dumps(fake.responses.requests)
    for customer in context.data.customers:
        for value in (customer.name, customer.email, customer.phone, customer.city):
            assert value not in serialized
    assert "customer_id" not in json.dumps(result)
    for tool in fake.responses.requests[0]["tools"]:
        assert "customer_id" not in tool["parameters"]["properties"]


def test_tool_business_error_is_sent_to_model_for_customer_answer(context):
    from emporio_support_agent.agent import SupportAgent

    fake = client(pending("lookup", function(arguments='{"product_id":999}')), final(text="I couldn't find that product."))
    reply = SupportAgent(context=context, client=fake).respond("Product 999?")
    result = json.loads(fake.responses.requests[1]["input"][0]["output"])
    assert result == {"ok": False, "error": {"code": "product_not_found", "message": "Product not found."}}
    assert reply.text == "I couldn't find that product."


@pytest.mark.parametrize("call", [
    function(arguments='DO-NOT-ECHO'), function(arguments='[]'),
    function(name="unapproved_tool"), function(call_id=""),
])
def test_invalid_calls_do_not_execute_tools_or_echo_model_input(context, monkeypatch, call):
    import emporio_support_agent.agent as module
    from emporio_support_agent.openai_adapter import OpenAIAdapterError

    def forbidden(*args):
        pytest.fail("Invalid function call reached the dispatcher")

    monkeypatch.setattr(module, "execute_tool", forbidden)
    fake = client(pending("bad", call))
    with pytest.raises((module.AgentResponseError, OpenAIAdapterError)) as caught:
        module.SupportAgent(context=context, client=fake).respond("Question")
    assert "DO-NOT-ECHO" not in str(caught.value)
    assert len(fake.responses.requests) == 1


def test_multiple_calls_are_processed_in_order_and_returned_together(context):
    from emporio_support_agent.agent import SupportAgent

    fake = client(pending("batch", function(call_id="one"), function(arguments='{"product_id":999}', call_id="two")), final())
    reply = SupportAgent(context=context, client=fake).respond("Two products")
    outputs = fake.responses.requests[1]["input"]
    assert [output["call_id"] for output in outputs] == ["one", "two"]
    assert json.loads(outputs[0]["output"])["data"]["product_id"] == 101
    assert json.loads(outputs[1]["output"])["error"]["code"] == "product_not_found"
    assert reply.tool_names == ("get_product_details", "get_product_details")
    assert reply.tool_call_count == 2


def test_default_round_limit_stops_before_fifth_execution(context, monkeypatch):
    import emporio_support_agent.agent as module

    executions = []
    original = module.execute_tool

    def record(*args):
        executions.append(args[1])
        return original(*args)

    monkeypatch.setattr(module, "execute_tool", record)
    fake = client(*(pending(str(index)) for index in range(5)))
    with pytest.raises(module.AgentLoopLimitError):
        module.SupportAgent(context=context, client=fake).respond("Keep looking")
    assert len(executions) == 4
    assert len(fake.responses.requests) == 5


def test_default_execution_limit_counts_all_calls_across_rounds(context, monkeypatch):
    import emporio_support_agent.agent as module

    executions = []
    original = module.execute_tool

    def record(*args):
        executions.append(args[1])
        return original(*args)

    monkeypatch.setattr(module, "execute_tool", record)
    fake = client(pending("eight", *(function(call_id=str(index)) for index in range(8))), pending("ninth"))
    with pytest.raises(module.AgentLoopLimitError):
        module.SupportAgent(context=context, client=fake).respond("Keep looking")
    assert len(executions) == 8
    assert len(fake.responses.requests) == 2


def test_execution_budget_rejects_whole_batch_before_partial_execution(context, monkeypatch):
    import emporio_support_agent.agent as module

    def forbidden(*args):
        pytest.fail("Over-budget batch reached the dispatcher")

    monkeypatch.setattr(module, "execute_tool", forbidden)
    fake = client(pending("batch", function(call_id="one"), function(call_id="two")))
    with pytest.raises(module.AgentLoopLimitError):
        module.SupportAgent(context=context, client=fake, max_tool_executions=1).respond("Question")
    assert len(fake.responses.requests) == 1


@pytest.mark.parametrize("message", ["", "  ", "\n\t", None, 1, [], True])
def test_invalid_messages_are_rejected_before_provider_call(context, message):
    from emporio_support_agent.agent import SupportAgent

    fake = client()
    with pytest.raises(ValueError):
        SupportAgent(context=context, client=fake).respond(message)
    assert fake.responses.requests == []


@pytest.mark.parametrize("response", [final(text=""), final(text="  "), final(status="incomplete"), final(status="failed"), final(response_id="")])
def test_unusable_responses_cannot_become_completed_turns(context, response):
    from emporio_support_agent.agent import AgentResponseError, SupportAgent

    fake = client(final("saved"), response, final("recovered"))
    agent = SupportAgent(context=context, client=fake)
    agent.respond("Hello")
    with pytest.raises(AgentResponseError):
        agent.respond("Question")
    agent.respond("Try again")
    assert fake.responses.requests[-1]["previous_response_id"] == "saved"


def provider_error(kind):
    request = httpx.Request("POST", "https://example.test/responses")
    if kind == "connection":
        return openai.APIConnectionError(message="DO-NOT-ECHO", request=request)
    cls, status = {
        "authentication": (openai.AuthenticationError, 401),
        "quota": (openai.RateLimitError, 429),
        "http": (openai.APIStatusError, 500),
    }[kind]
    return cls("DO-NOT-ECHO", response=httpx.Response(status, request=request), body={"secret": "DO-NOT-ECHO"})


@pytest.mark.parametrize("kind", ["authentication", "quota", "connection", "http"])
def test_provider_failures_are_safe_chained_and_keep_last_completed_session(context, kind):
    from emporio_support_agent.agent import AgentProviderError, SupportAgent

    error = provider_error(kind)
    fake = client(final("saved"), pending("intermediate"), error, final("recovered"))
    agent = SupportAgent(context=context, client=fake)
    agent.respond("Hello")
    with pytest.raises(AgentProviderError) as caught:
        agent.respond("Question")
    assert "DO-NOT-ECHO" not in str(caught.value)
    assert caught.value.__cause__ is error
    agent.respond("Try again")
    assert fake.responses.requests[-1]["previous_response_id"] == "saved"


def test_loop_failure_also_preserves_last_completed_turn(context):
    from emporio_support_agent.agent import AgentLoopLimitError, SupportAgent

    fake = client(final("saved"), pending("intermediate"), final("recovered"))
    agent = SupportAgent(context=context, client=fake, max_tool_rounds=0)
    agent.respond("Hello")
    with pytest.raises(AgentLoopLimitError):
        agent.respond("Question")
    agent.respond("Again")
    assert fake.responses.requests[-1]["previous_response_id"] == "saved"


@pytest.mark.parametrize("field,value", [("max_tool_rounds", -1), ("max_tool_executions", True), ("max_tool_rounds", 1.5), ("model", " ")])
def test_invalid_configuration_fails_before_provider_call(context, field, value):
    from emporio_support_agent.agent import SupportAgent

    fake = client()
    with pytest.raises(ValueError):
        SupportAgent(context=context, client=fake, **{field: value})
    assert fake.responses.requests == []


def test_programmatic_model_override_is_sent_without_discovery(context):
    from emporio_support_agent.agent import SupportAgent

    fake = client(final())
    SupportAgent(context=context, client=fake, model="test-model").respond("Hello")
    assert fake.responses.requests[0]["model"] == "test-model"


def test_default_client_uses_environment_with_bounded_timeout_and_retries(context, monkeypatch):
    import emporio_support_agent.agent as module

    fake = client(final())
    settings = []

    def construct(**kwargs):
        settings.append(kwargs)
        return fake

    monkeypatch.setattr(module, "OpenAI", construct)
    module.SupportAgent(context=context).respond("Hello")
    assert len(settings) == 1
    assert settings[0]["timeout"] > 0
    assert settings[0]["max_retries"] == 0
    assert "api_key" not in settings[0]


def test_missing_environment_key_becomes_safe_project_error(context, monkeypatch):
    import emporio_support_agent.agent as module

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(module.AgentProviderError):
        module.SupportAgent(context=context)


def test_instructions_explicitly_cover_required_grounding_and_persona():
    from emporio_support_agent.agent import SYSTEM_INSTRUCTIONS

    text = SYSTEM_INSTRUCTIONS.lower()
    for requirement in (
        "empório da música", "friendly", "language", "prices", "availability",
        "order status", "tracking", "estimated delivery", "actual receipt",
        "search_store_policies", "returns", "conflict", "customer_id",
        "transactions", "accessories", "python", "untrusted",
    ):
        assert requirement in text

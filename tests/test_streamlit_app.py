import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from emporio_support_agent.agent import AgentLoopLimitError, AgentProviderError, AgentReply, AgentResponseError
from emporio_support_agent.data import DataLoadError
from emporio_support_agent.openai_adapter import OpenAIAdapterError
from emporio_support_agent.policies import PolicyLoadError


def render_demo(argv):
    from emporio_support_agent.streamlit_app import main

    main(argv)


def test_streamlit_is_an_optional_extra_and_core_dependencies_are_preserved():
    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    project = config["project"]
    assert project["dependencies"] == ["pypdf==6.21.4", "openai==3.42.0"]
    assert project["optional-dependencies"]["dev"] == ["pytest==9.2.0"]
    assert project["optional-dependencies"]["ui"] == ["streamlit==1.66.1"]
    assert project["scripts"]["emporio-support"] == "emporio_support_agent.cli:main"


@pytest.fixture
def ui(monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    import emporio_support_agent.streamlit_app as module

    monkeypatch.setenv("OPENAI_API_KEY", "UI-TEST-SECRET")
    data = SimpleNamespace(customers=[SimpleNamespace(customer_id=301, name="PRIVATE-CUSTOMER", email="private@example.test", phone="PRIVATE-PHONE")])
    policy = object()
    calls = {"data": [], "policy": [], "agents": []}

    def load_data(path):
        calls["data"].append(path)
        return data

    def load_policy(path):
        calls["policy"].append(path)
        return policy

    class FakeAgent:
        def __init__(self, *, context):
            self.context = context
            self.messages = []
            calls["agents"].append(self)

        def respond(self, message):
            self.messages.append(message)
            return AgentReply(f"Answer: {message}", "INTERNAL-RESPONSE-ID", ("INTERNAL-TOOL",), 99)

    monkeypatch.setattr(module, "load_store_data", load_data)
    monkeypatch.setattr(module, "load_policy_pdf", load_policy)
    monkeypatch.setattr(module, "SupportAgent", FakeAgent)

    def app(argv=None):
        if argv is None:
            argv = ["--data-dir", "demo source/csv", "--policy-pdf", "demo source/políticas.pdf", "--customer-id", "301"]
        return AppTest.from_function(render_demo, args=(argv,), default_timeout=10)

    return module, calls, app, data, policy


def test_page_initialization_reuses_loaders_and_does_not_request_a_response(ui):
    _, calls, app, data, policy = ui
    at = app().run()
    assert not at.exception and not at.error
    assert calls["data"] == [Path("demo source/csv")]
    assert calls["policy"] == [Path("demo source/políticas.pdf")]
    assert len(calls["agents"]) == 1
    agent = calls["agents"][0]
    assert agent.context.data is data and agent.context.policies is policy
    assert agent.context.customer_id == 301
    assert agent.messages == []
    assert at.title[0].value == "Empório da Música"
    assert len(at.chat_input) == 1
    at.run()
    assert len(calls["agents"]) == 1 and len(calls["data"]) == 1


def test_visible_history_order_and_same_agent_survive_multiple_reruns(ui):
    _, calls, app, _, _ = ui
    at = app().run()
    at.chat_input[0].set_value("Hello").run()
    at.chat_input[0].set_value("What about Saturday?").run()
    assert not at.exception
    assert len(calls["agents"]) == 1
    assert calls["agents"][0].messages == ["Hello", "What about Saturday?"]
    assert [(message.name, message.markdown[0].value) for message in at.chat_message] == [
        ("user", "Hello"), ("assistant", "Answer: Hello"),
        ("user", "What about Saturday?"), ("assistant", "Answer: What about Saturday?"),
    ]
    assert at.session_state["_support_messages"] == [
        {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Answer: Hello"},
        {"role": "user", "content": "What about Saturday?"}, {"role": "assistant", "content": "Answer: What about Saturday?"},
    ]


def test_reset_discards_history_and_agent_but_preserves_unrelated_state(ui):
    _, calls, app, _, _ = ui
    at = app().run()
    at.chat_input[0].set_value("Hello").run()
    old_agent = calls["agents"][0]
    at.session_state["unrelated"] = "keep"
    at.button[0].click().run()
    assert not at.exception and len(at.chat_message) == 0
    assert at.session_state["_support_messages"] == []
    assert at.session_state["unrelated"] == "keep"
    at.chat_input[0].set_value("New topic").run()
    assert len(calls["agents"]) == 2
    assert calls["agents"][1] is not old_agent
    assert old_agent.messages == ["Hello"]
    assert calls["agents"][1].messages == ["New topic"]


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_key_blocks_initialization_and_chat(ui, monkeypatch, value):
    _, calls, app, _, _ = ui
    if value is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", value)
    at = app().run()
    assert not at.exception
    assert calls["agents"] == []
    assert "OPENAI_API_KEY" in at.error[0].value
    assert len(at.chat_input) == 0


@pytest.mark.parametrize("target,error", [
    ("load_store_data", DataLoadError("source unavailable")),
    ("load_policy_pdf", PolicyLoadError("source unavailable")),
    ("load_store_data", OSError("DO-NOT-ECHO")),
    ("SupportAgent", AgentProviderError("DO-NOT-ECHO")),
])
def test_source_and_initialization_failures_render_controlled_errors(ui, monkeypatch, target, error):
    module, calls, app, _, _ = ui

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(module, target, fail)
    at = app().run()
    assert not at.exception and len(at.error) == 1
    assert len(at.chat_input) == 0 and calls["agents"] == []
    assert "DO-NOT-ECHO" not in at.error[0].value


@pytest.mark.parametrize("error", [AgentProviderError("DO-NOT-ECHO"), AgentLoopLimitError("DO-NOT-ECHO"), AgentResponseError("DO-NOT-ECHO"), OpenAIAdapterError("DO-NOT-ECHO")])
def test_failed_turn_keeps_successful_messages_without_fabricating_assistant(ui, monkeypatch, error):
    _, calls, app, _, _ = ui
    at = app().run()
    at.chat_input[0].set_value("Hello").run()
    agent = calls["agents"][0]

    def fail(message):
        raise error

    monkeypatch.setattr(agent, "respond", fail)
    at.chat_input[0].set_value("Failed question").run()
    assert not at.exception and len(at.error) == 1
    assert "DO-NOT-ECHO" not in at.error[0].value
    assert at.session_state["_support_messages"] == [
        {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Answer: Hello"},
        {"role": "user", "content": "Failed question"},
    ]
    assert len(calls["agents"]) == 1


@pytest.mark.parametrize("prompt", ["", "   ", "\t\n"])
def test_blank_prompts_never_call_agent(ui, prompt):
    _, calls, app, _, _ = ui
    at = app().run()
    at.chat_input[0].set_value(prompt).run()
    assert not at.exception
    assert calls["agents"][0].messages == []
    assert at.session_state["_support_messages"] == []


def test_optional_customer_identity_remains_none(ui):
    _, calls, app, _, _ = ui
    at = app(["--data-dir", "demo", "--policy-pdf", "demo.pdf"]).run()
    assert not at.exception
    assert calls["agents"][0].context.customer_id is None


@pytest.mark.parametrize("argv", [[], ["--data-dir", "demo"], ["--data-dir", "demo", "--policy-pdf", "demo.pdf", "--customer-id", "0"]])
def test_invalid_configuration_renders_ui_error_instead_of_traceback(ui, argv):
    _, calls, app, _, _ = ui
    at = app(argv).run()
    assert not at.exception and len(at.error) == 1
    assert calls["agents"] == [] and len(at.chat_input) == 0


def test_only_customer_text_is_rendered_or_stored_in_display_history(ui):
    _, _, app, _, _ = ui
    at = app().run()
    at.chat_input[0].set_value("Hello").run()
    visible = " ".join(element.value for kind in (at.title, at.caption, at.markdown, at.error) for element in kind)
    for private in ("301", "UI-TEST-SECRET", "PRIVATE-CUSTOMER", "private@example.test", "PRIVATE-PHONE", "INTERNAL-RESPONSE-ID", "INTERNAL-TOOL"):
        assert private not in visible
    assert all(set(message) == {"role", "content"} for message in at.session_state["_support_messages"])

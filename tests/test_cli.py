from pathlib import Path

import pytest

from emporio_support_agent.agent import AgentLoopLimitError, AgentProviderError, AgentReply, AgentResponseError
from emporio_support_agent.data import DataLoadError
from emporio_support_agent.openai_adapter import OpenAIAdapterError
from emporio_support_agent.policies import PolicyLoadError


@pytest.mark.parametrize("argv", [[], ["--data-dir", "data"], ["--policy-pdf", "policy.pdf"]])
def test_parser_requires_both_source_paths(argv, capsys):
    from emporio_support_agent.cli import build_parser

    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(argv)
    assert caught.value.code == 2
    assert "required" in capsys.readouterr().err


def test_parser_accepts_explicit_unicode_paths_and_positive_demo_identity():
    from emporio_support_agent.cli import build_parser

    parsed = build_parser().parse_args([
        "--data-dir", "source files/csv", "--policy-pdf", "source files/políticas.pdf", "--customer-id", "301",
    ])
    assert parsed.data_dir == Path("source files/csv")
    assert parsed.policy_pdf == Path("source files/políticas.pdf")
    assert parsed.customer_id == 301


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer", "1.5"])
def test_parser_rejects_invalid_customer_identity(value, capsys):
    from emporio_support_agent.cli import build_parser

    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(["--data-dir", "data", "--policy-pdf", "policy.pdf", "--customer-id", value])
    assert caught.value.code == 2
    assert "positive integer" in capsys.readouterr().err


def test_parser_has_no_api_key_argument(capsys):
    from emporio_support_agent.cli import build_parser

    parser = build_parser()
    assert "--api-key" not in parser.format_help()
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["--data-dir", "data", "--policy-pdf", "policy.pdf", "--api-key", "test-placeholder"])
    assert caught.value.code == 2
    assert "unrecognized" in capsys.readouterr().err


@pytest.fixture
def session(monkeypatch, tmp_path):
    import emporio_support_agent.cli as module

    monkeypatch.setenv("OPENAI_API_KEY", "CLI-TEST-SECRET")
    loaded_data, loaded_policy = object(), object()
    calls = {"data": [], "policy": [], "agents": []}

    def data_loader(path):
        calls["data"].append(path)
        return loaded_data

    def policy_loader(path):
        calls["policy"].append(path)
        return loaded_policy

    class FakeAgent:
        def __init__(self, *, context):
            self.context = context
            self.messages = []
            calls["agents"].append(self)

        def respond(self, message):
            self.messages.append(message)
            return AgentReply(f"Answer {len(self.messages)}", "INTERNAL-ID", ("INTERNAL-TOOL",), 99)

    monkeypatch.setattr(module, "load_store_data", data_loader)
    monkeypatch.setattr(module, "load_policy_pdf", policy_loader)
    monkeypatch.setattr(module, "SupportAgent", FakeAgent)
    data_path, policy_path = tmp_path / "source files", tmp_path / "políticas.pdf"
    return module, calls, ["--data-dir", str(data_path), "--policy-pdf", str(policy_path)], loaded_data, loaded_policy


def inputs(monkeypatch, *values):
    script = iter(values)

    def read(prompt):
        value = next(script)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", read)


def test_startup_uses_public_loaders_and_one_agent_for_multiple_turns(session, monkeypatch, capsys):
    module, calls, argv, data, policy = session
    inputs(monkeypatch, "Hello", "What about Saturday?", "exit")
    assert module.run_cli([*argv, "--customer-id", "301"]) == 0
    assert calls["data"] == [Path(argv[1])]
    assert calls["policy"] == [Path(argv[3])]
    assert len(calls["agents"]) == 1
    agent = calls["agents"][0]
    assert agent.context.data is data and agent.context.policies is policy
    assert agent.context.customer_id == 301
    assert agent.messages == ["Hello", "What about Saturday?"]
    captured = capsys.readouterr()
    assert "Agent: Answer 1" in captured.out and "Agent: Answer 2" in captured.out
    assert captured.err == ""
    for private in ("301", "INTERNAL-ID", "INTERNAL-TOOL", "CLI-TEST-SECRET"):
        assert private not in captured.out


def test_customer_identity_is_optional(session, monkeypatch):
    module, calls, argv, _, _ = session
    inputs(monkeypatch, "Product question", "quit")
    assert module.run_cli(argv) == 0
    assert calls["agents"][0].context.customer_id is None
    assert calls["agents"][0].messages == ["Product question"]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_fails_before_agent_construction_without_secrets(session, monkeypatch, capsys, value):
    module, calls, argv, _, _ = session
    if value is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", value)
    assert module.run_cli(argv) != 0
    assert calls["agents"] == []
    captured = capsys.readouterr()
    assert "OPENAI_API_KEY" in captured.err and "configured" in captured.err
    assert "Traceback" not in captured.err and "CLI-TEST-SECRET" not in captured.err


def test_empty_inputs_and_termination_never_reach_agent(session, monkeypatch):
    module, calls, argv, _, _ = session
    inputs(monkeypatch, "", "  ", "\t", "A real question", "  ExIt  ")
    assert module.run_cli(argv) == 0
    assert calls["agents"][0].messages == ["A real question"]


@pytest.mark.parametrize("termination", ["exit", " QUIT ", EOFError(), KeyboardInterrupt()])
def test_clean_termination_returns_zero_without_provider_message(session, monkeypatch, capsys, termination):
    module, calls, argv, _, _ = session
    inputs(monkeypatch, termination)
    assert module.run_cli(argv) == 0
    assert calls["agents"][0].messages == []
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("target,error", [
    ("load_store_data", DataLoadError("CSV source unavailable")),
    ("load_policy_pdf", PolicyLoadError("PDF source unavailable")),
    ("load_store_data", OSError("DO-NOT-ECHO")),
])
def test_expected_source_errors_are_concise_and_stop_startup(session, monkeypatch, capsys, target, error):
    module, calls, argv, _, _ = session

    def fail(path):
        raise error

    monkeypatch.setattr(module, target, fail)
    assert module.run_cli(argv) != 0
    assert calls["agents"] == []
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "Traceback" not in captured.err and "DO-NOT-ECHO" not in captured.err


@pytest.mark.parametrize("error", [
    AgentProviderError("Provider request failed"), AgentLoopLimitError("Tool limit reached"),
    AgentResponseError("No usable response"), OpenAIAdapterError("Invalid JSON object"),
])
def test_expected_agent_errors_go_to_stderr_without_traceback_or_cause(session, monkeypatch, capsys, error):
    module, calls, argv, _, _ = session
    error.__cause__ = RuntimeError("DO-NOT-ECHO")

    def fail(self, message):
        raise error

    monkeypatch.setattr(module.SupportAgent, "respond", fail)
    inputs(monkeypatch, "Question")
    assert module.run_cli(argv) != 0
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "Traceback" not in captured.err and "DO-NOT-ECHO" not in captured.err
    assert "CLI-TEST-SECRET" not in captured.out + captured.err


def test_agent_construction_error_is_presented_safely(session, monkeypatch, capsys):
    module, _, argv, _, _ = session

    def fail(**kwargs):
        raise AgentProviderError("Client configuration failed")

    monkeypatch.setattr(module, "SupportAgent", fail)
    assert module.run_cli(argv) != 0
    assert capsys.readouterr().err.strip()


def test_ctrl_c_during_agent_request_also_exits_cleanly(session, monkeypatch):
    module, _, argv, _, _ = session

    def interrupt(self, message):
        raise KeyboardInterrupt

    monkeypatch.setattr(module.SupportAgent, "respond", interrupt)
    inputs(monkeypatch, "Question")
    assert module.run_cli(argv) == 0


def test_unexpected_programming_errors_remain_diagnosable(session, monkeypatch):
    module, _, argv, _, _ = session

    def broken(self, message):
        raise TypeError("Unexpected programming bug")

    monkeypatch.setattr(module.SupportAgent, "respond", broken)
    inputs(monkeypatch, "Question")
    with pytest.raises(TypeError):
        module.run_cli(argv)


def test_main_translates_runner_result_to_process_status(monkeypatch):
    import emporio_support_agent.cli as module

    monkeypatch.setattr(module, "run_cli", lambda: 7)
    with pytest.raises(SystemExit) as caught:
        module.main()
    assert caught.value.code == 7

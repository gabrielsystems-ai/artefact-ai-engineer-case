"""Minimal interactive terminal orchestration over the existing support agent."""

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .agent import AgentLoopLimitError, AgentProviderError, AgentResponseError, SupportAgent
from .data import DataLoadError, load_store_data
from .openai_adapter import OpenAIAdapterError
from .policies import PolicyLoadError, load_policy_pdf
from .tools import ToolContext


def _positive_customer_id(value: str) -> int:
    try:
        identity = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("customer ID must be a positive integer") from None
    if identity <= 0:
        raise argparse.ArgumentTypeError("customer ID must be a positive integer")
    return identity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emporio-support",
        description="Interactive Emporio da Musica support agent.",
        allow_abbrev=False,
    )
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory containing the six provided CSV datasets.")
    parser.add_argument("--policy-pdf", type=Path, required=True, help="Path to the provided store-policy PDF.")
    parser.add_argument("--customer-id", type=_positive_customer_id, help="Optional simulated customer identity for orders; not authentication.")
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Error: OPENAI_API_KEY is not configured. Set it in your environment before starting the CLI.", file=sys.stderr)
        return 1
    try:
        data = load_store_data(args.data_dir)
        policies = load_policy_pdf(args.policy_pdf)
        context = ToolContext(data=data, policies=policies, customer_id=args.customer_id)
        agent = SupportAgent(context=context)
        print("Emporio da Musica Support Agent\nType 'exit' or 'quit' to end the session.")
        while True:
            message = input("You: ").strip()
            if message.casefold() in {"exit", "quit"}:
                print("Goodbye.")
                return 0
            if not message:
                continue
            reply = agent.respond(message)
            print(f"Agent: {reply.text}")
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        return 0
    except (DataLoadError, PolicyLoadError) as exc:
        print(f"Error loading sources: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: Could not read the source paths or terminal streams.", file=sys.stderr)
        return 1
    except AgentProviderError:
        print("Error: Provider request failed. Check API access and try again.", file=sys.stderr)
        return 1
    except (AgentLoopLimitError, AgentResponseError, OpenAIAdapterError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run_cli())

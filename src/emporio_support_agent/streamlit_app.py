"""Optional, session-scoped chat presentation over the existing support runtime."""

import os
from collections.abc import Sequence
from contextlib import redirect_stderr
from io import StringIO

import streamlit as st

from emporio_support_agent.agent import AgentLoopLimitError, AgentProviderError, AgentResponseError, SupportAgent
from emporio_support_agent.cli import build_parser
from emporio_support_agent.data import DataLoadError, load_store_data
from emporio_support_agent.openai_adapter import OpenAIAdapterError
from emporio_support_agent.policies import PolicyLoadError, load_policy_pdf
from emporio_support_agent.tools import ToolContext


_STYLE = """
<style>
[data-testid="stMainBlockContainer"], [data-testid="stBottomBlockContainer"] {
    max-width: 52rem;
}
[data-testid="stMainBlockContainer"] { padding-top: 1.75rem; }
.st-key-support_header h1 {
    font-size: clamp(1.9rem, 4vw, 2.7rem);
    font-weight: 500;
    line-height: 1.15;
    letter-spacing: -0.025em;
}
.st-key-support_header [data-testid="stCaptionContainer"] { color: inherit; }
.st-key-new_conversation button { min-height: 2.75rem; padding: 0.5rem 0.85rem; }
[data-testid="stMainBlockContainer"] hr { margin: 0.25rem 0 0.75rem; }
[data-testid="stChatMessage"] {
    /* Follow Streamlit's actual foreground, including manual theme changes. */
    color: inherit;
    background-color: transparent;
    background-color: color-mix(in srgb, currentColor 6%, transparent);
    border-radius: 0.75rem;
    padding: 1rem;
    min-width: 0;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
    color: inherit;
    line-height: 1.6;
    overflow-wrap: anywhere;
}
[data-testid="stChatMessage"] :where(p, ul, ol, li, strong, em, blockquote) { color: inherit; }
[data-testid="stChatMessage"] a { text-decoration: underline; text-underline-offset: 0.15em; }
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] { padding-top: 1.25rem; }
    [data-testid="stChatMessage"] { padding: 0.8rem; }
}
</style>
"""


def _new_conversation() -> None:
    st.session_state.pop("_support_agent", None)
    st.session_state["_support_messages"] = []


def _message(role: str, content: str) -> None:
    avatar = ":material/person:" if role == "user" else ":material/music_note:"
    with st.chat_message(role, avatar=avatar):
        st.markdown(content)


def main(argv: Sequence[str] | None = None) -> None:
    st.set_page_config(page_title="Empório da Música | Support", layout="centered")
    st.markdown(_STYLE, unsafe_allow_html=True)
    with st.container(key="support_header", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
        with st.container(width="content"):
            st.title("Empório da Música")
            st.caption("AI Customer Support")
        st.button("New conversation", key="new_conversation", type="secondary", icon=":material/add:",
                  on_click=_new_conversation, help="Reset this local demo conversation. Stored Responses are not deleted.")
    st.write("A little guidance for your next instrument. Ask about prices, availability, orders or store policies.")
    st.divider()

    try:
        # Reuse the CLI's path/identity semantics without printing parser errors.
        with redirect_stderr(StringIO()):
            args = build_parser().parse_args(argv)
    except SystemExit:
        st.error("Provide --data-dir and --policy-pdf after Streamlit's -- separator. Any customer ID must be a positive integer.")
        return
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        st.error("OPENAI_API_KEY is not configured. Set it in the environment before starting the demo.")
        return
    try:
        if "_support_agent" not in st.session_state:
            data = load_store_data(args.data_dir)
            policies = load_policy_pdf(args.policy_pdf)
            st.session_state["_support_agent"] = SupportAgent(
                context=ToolContext(data=data, policies=policies, customer_id=args.customer_id),
            )
    except (DataLoadError, PolicyLoadError, OSError):
        st.error("Store information could not be loaded. Check the CSV directory and policy PDF used to launch this demo.")
        return
    except AgentProviderError:
        st.error("The support service could not be initialized. Check the API configuration and try again.")
        return

    messages = st.session_state.setdefault("_support_messages", [])
    if not messages:
        st.subheader("How can we help?")
        st.write("Ask about an instrument, your order, delivery or one of our store policies.")
        st.caption("A support prototype using the supplied store information.")
    for message in messages:
        _message(message["role"], message["content"])

    prompt = st.chat_input("Ask about instruments or store policies")
    if not isinstance(prompt, str) or not prompt.strip():
        return
    prompt = prompt.strip()
    messages.append({"role": "user", "content": prompt})
    _message("user", prompt)
    try:
        with st.spinner("Checking store information..."):
            reply = st.session_state["_support_agent"].respond(prompt)
    except AgentProviderError:
        st.error("We couldn't reach the support service. Please try again.")
        return
    except (AgentLoopLimitError, AgentResponseError, OpenAIAdapterError):
        st.error("We couldn't complete that request. Please try a more specific question.")
        return
    messages.append({"role": "assistant", "content": reply.text})
    _message("assistant", reply.text)


if __name__ == "__main__":
    main()

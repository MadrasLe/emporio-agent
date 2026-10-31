"""A small facade used by the CLI, the Streamlit UI and the evals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from .graph import CRITIQUE_NAME, build_graph, text_of
from .runtime import Runtime

RECURSION_LIMIT = 40


@dataclass
class TurnResult:
    answer: str
    audit: list[dict] = field(default_factory=list)

    @property
    def tools_called(self) -> list[str]:
        return [event["tool"] for event in self.audit if event.get("type") == "tool"]


class Assistant:
    def __init__(self, runtime: Runtime, checkpointer: Any = None):
        self.runtime = runtime
        self.graph = build_graph(runtime, checkpointer or InMemorySaver())

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}

    def reply(self, thread_id: str, text: str) -> TurnResult:
        state = self.graph.invoke(
            {"messages": [HumanMessage(text)], "turn_audit": [], "revisions": 0},
            self._config(thread_id),
        )
        return TurnResult(text_of(state["messages"][-1]), state.get("turn_audit") or [])

    def history(self, thread_id: str) -> list[tuple[str, str]]:
        """(role, text) pairs a customer would see: no tool traffic, no internal critiques."""

        values = self.graph.get_state(self._config(thread_id)).values
        pairs = []
        for message in values.get("messages", []):
            if isinstance(message, HumanMessage) and message.name != CRITIQUE_NAME:
                pairs.append(("user", text_of(message)))
            elif isinstance(message, AIMessage) and not message.tool_calls and text_of(message).strip():
                pairs.append(("assistant", text_of(message)))
        return pairs

    def session_state(self, thread_id: str) -> dict:
        values = self.graph.get_state(self._config(thread_id)).values
        return {key: values.get(key) for key in ("identity_state", "customer_id", "failed_attempts", "tickets")}

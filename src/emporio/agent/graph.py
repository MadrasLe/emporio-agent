"""The LangGraph state machine that runs one customer turn.

    START -> agent --(tool calls)--> tools -> agent ...
             agent --(answer)------> constitution --(ok)--> END
                                     constitution --(violation, 1st time)--> agent (with critique)
                                     constitution --(violation again)------> END (safe fallback)

The LLM only orchestrates and writes; tools compute; the constitution checks.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
    trim_messages,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from pydantic import ValidationError

from .constitution import FALLBACK_ANSWER, check_answer, critique_message, evaluate_tool_call
from .prompts import build_system_prompt
from .runtime import Runtime
from .tools import ToolContext, to_json

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6  # per customer turn; after that the model must answer
MAX_REVISIONS = 1
MAX_HISTORY_MESSAGES = 40
CRITIQUE_NAME = "constitution"
SESSION_KEYS = ("identity_state", "customer_id", "failed_attempts", "tickets")


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    identity_state: str
    customer_id: int | None
    failed_attempts: int
    tickets: list[str]
    turn_audit: list[dict]  # reset at every turn; shown by the CLI/UI
    revisions: int


def text_of(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)


def _current_turn(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Messages since the last real customer message."""

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if isinstance(message, HumanMessage) and message.name != CRITIQUE_NAME:
            return messages[index:]
    return messages


def _session(state: AgentState) -> dict:
    return {key: state.get(key) for key in SESSION_KEYS}


def build_graph(runtime: Runtime, checkpointer: Any = None):
    tool_schemas = [spec.openai_schema() for spec in runtime.tools.values()]
    llm_with_tools = runtime.llm.bind_tools(tool_schemas)

    def agent(state: AgentState) -> dict:
        system = build_system_prompt(runtime.knowledge, runtime.data, runtime.now(), _session(state))
        history = trim_messages(state["messages"], max_tokens=MAX_HISTORY_MESSAGES, token_counter=len,
                                strategy="last", start_on="human")
        rounds = sum(1 for m in _current_turn(state["messages"]) if isinstance(m, AIMessage) and m.tool_calls)
        model = llm_with_tools if rounds < MAX_TOOL_ROUNDS else runtime.llm
        response = model.invoke([SystemMessage(system), *history])
        return {"messages": [response]}

    def tools(state: AgentState) -> dict:
        call_message = state["messages"][-1]
        session = _session(state)
        audit = list(state.get("turn_audit") or [])
        results: list[ToolMessage] = []

        for call in call_message.tool_calls:
            name, args = call["name"], call.get("args") or {}
            spec = runtime.tools.get(name)
            gate = evaluate_tool_call(spec, name, args, session, runtime.data)
            event: dict = {"type": "tool", "tool": name, "args": args, "gate": gate.explain()}

            if not gate.decision.allowed:
                content: dict = {"bloqueado_pela_constituicao": gate.decision.reason}
            else:
                try:
                    parsed = spec.args.model_validate(args)
                    ctx = ToolContext(runtime.data, runtime.knowledge, runtime.now(), session, runtime.tickets_path)
                    outcome = spec.handler(parsed, ctx)
                    content = outcome.content
                    session.update(outcome.state_updates)
                    if outcome.decision:
                        event["decision"] = outcome.decision
                except ValidationError as exc:
                    content = {"erro": "argumentos inválidos",
                               "detalhes": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]}
                except Exception:  # a tool bug must not crash the conversation
                    log.exception("tool %s failed", name)
                    content = {"erro": "falha interna ao consultar o sistema; ofereça encaminhar para a equipe"}

            event["result"] = content
            audit.append(event)
            results.append(ToolMessage(content=to_json(content), tool_call_id=call["id"], name=name))

        return {"messages": results, "turn_audit": audit, **session}

    def constitution(state: AgentState) -> Command:
        messages = state["messages"]
        draft = messages[-1]
        turn = _current_turn(messages)
        evidence = "\n".join(text_of(m) for m in messages if isinstance(m, ToolMessage))
        customer_text = "\n".join(text_of(m) for m in messages
                                  if isinstance(m, HumanMessage) and m.name != CRITIQUE_NAME)
        violations = check_answer(text_of(draft), evidence=evidence, customer_text=customer_text,
                                  data=runtime.data, verified_customer_id=state.get("customer_id"))
        audit = list(state.get("turn_audit") or [])
        revisions = state.get("revisions") or 0
        critiques = [m for m in turn if isinstance(m, HumanMessage) and m.name == CRITIQUE_NAME]

        if not violations:
            audit.append({"type": "constitution", "ok": True, "revised": revisions > 0})
            # The answer is good: drop the internal critique so the history stays clean.
            return Command(goto=END, update={"turn_audit": audit,
                                             "messages": [RemoveMessage(id=m.id) for m in critiques]})

        audit.append({"type": "constitution", "ok": False, "violations": [v.to_dict() for v in violations],
                      "draft": text_of(draft)})
        if revisions < MAX_REVISIONS:
            critique = HumanMessage(critique_message(violations), name=CRITIQUE_NAME)
            return Command(goto="agent", update={
                "turn_audit": audit, "revisions": revisions + 1,
                "messages": [RemoveMessage(id=draft.id), critique],
            })

        audit.append({"type": "constitution", "fallback": True})
        return Command(goto=END, update={
            "turn_audit": audit,
            "messages": [RemoveMessage(id=draft.id), *[RemoveMessage(id=m.id) for m in critiques],
                         AIMessage(FALLBACK_ANSWER)],
        })

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if isinstance(last, AIMessage) and last.tool_calls else "constitution"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools)
    graph.add_node("constitution", constitution, destinations=("agent", END))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, ["tools", "constitution"])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def audit_to_json(audit: list[dict]) -> str:
    return json.dumps(audit, ensure_ascii=False, indent=2, default=str)

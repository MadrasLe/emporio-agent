"""Typed decisions and audit traces.

Adapted from JadeAgent (https://github.com/MadrasLe/JadeAgent,
``jadeagent/deterministic/types.py``), trimmed to what this project needs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


def json_safe(value: Any) -> Any:
    """Convert runtime values into stable, JSON-compatible structures."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return [json_safe(item) for item in sorted(value, key=repr)]
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return json_safe(to_dict())
    return repr(value)


def canonical_json_hash(value: Any) -> str:
    payload = json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DecisionKind(str, Enum):
    """The finite set of outcomes a decision policy can emit."""

    ACTION = "action"
    FINAL = "final"
    REJECT = "reject"
    ESCALATE = "escalate"
    WAIT = "wait"


@dataclass
class Decision:
    """A structured policy outcome, independent from its execution mechanism."""

    kind: DecisionKind | str
    reason: str = ""
    action: str = ""
    value: Any = None
    state_updates: dict[str, Any] = field(default_factory=dict)
    rule_id: str = ""

    def __post_init__(self) -> None:
        self.kind = DecisionKind(self.kind)
        self.state_updates = dict(self.state_updates)
        if self.kind == DecisionKind.ACTION and not self.action.strip():
            raise ValueError("action decisions require a non-empty action name")

    @classmethod
    def act(cls, action: str, *, reason: str = "", value: Any = None,
            state_updates: dict[str, Any] | None = None) -> Decision:
        return cls(DecisionKind.ACTION, reason=reason, action=action, value=value,
                   state_updates=dict(state_updates or {}))

    @classmethod
    def finish(cls, value: Any = None, *, reason: str = "",
               state_updates: dict[str, Any] | None = None) -> Decision:
        return cls(DecisionKind.FINAL, reason=reason, value=value,
                   state_updates=dict(state_updates or {}))

    @classmethod
    def reject(cls, reason: str, *, value: Any = None,
               state_updates: dict[str, Any] | None = None) -> Decision:
        return cls(DecisionKind.REJECT, reason=reason, value=value,
                   state_updates=dict(state_updates or {}))

    @classmethod
    def escalate(cls, reason: str, *, value: Any = None,
                 state_updates: dict[str, Any] | None = None) -> Decision:
        return cls(DecisionKind.ESCALATE, reason=reason, value=value,
                   state_updates=dict(state_updates or {}))

    @classmethod
    def pause(cls, reason: str, *, value: Any = None) -> Decision:
        return cls(DecisionKind.WAIT, reason=reason, value=value)

    @property
    def allowed(self) -> bool:
        return self.kind in (DecisionKind.ACTION, DecisionKind.FINAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "action": self.action,
            "value": json_safe(self.value),
            "state_updates": json_safe(self.state_updates),
            "rule_id": self.rule_id,
        }


@dataclass
class DecisionTraceStep:
    """One explainable evaluation step inside a policy."""

    step_id: str
    kind: str
    outcome: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "outcome": json_safe(self.outcome),
            "detail": self.detail,
        }


@dataclass
class DecisionTrace:
    """Complete evidence explaining why a policy selected a decision."""

    policy_id: str
    observation_hash: str
    state_hash: str
    steps: list[DecisionTraceStep] = field(default_factory=list)
    decision: Decision | None = None

    def add(self, step_id: str, kind: str, *, outcome: Any = None, detail: str = "") -> None:
        self.steps.append(DecisionTraceStep(str(step_id), str(kind), outcome, str(detail)))

    def finish(self, decision: Decision) -> DecisionTrace:
        self.decision = decision
        return self

    @property
    def trace_hash(self) -> str:
        """Stable hash: equal inputs and equal rules give an equal hash."""

        return canonical_json_hash({
            "policy_id": self.policy_id,
            "observation_hash": self.observation_hash,
            "state_hash": self.state_hash,
            "steps": [step.to_dict() for step in self.steps],
            "decision": self.decision.to_dict() if self.decision else None,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "trace_hash": self.trace_hash,
            "steps": [step.to_dict() for step in self.steps],
            "decision": self.decision.to_dict() if self.decision else None,
        }


@dataclass
class PolicyResult:
    decision: Decision
    trace: DecisionTrace

    def explain(self) -> dict[str, Any]:
        """Compact, LLM-friendly view: the outcome and the rules that were checked."""

        checked = [
            {"rule": step.step_id, "matched": step.outcome, "detail": step.detail}
            for step in self.trace.steps
            if step.kind in ("rule", "transition_guard")
        ]
        return {
            "outcome": self.decision.kind.value,
            "rule_id": self.decision.rule_id,
            "reason": self.decision.reason,
            "checked": checked,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.to_dict(), "trace": self.trace.to_dict()}

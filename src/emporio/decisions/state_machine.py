"""Finite-state-machine policies with guarded, auditable transitions.

Adapted from JadeAgent (``jadeagent/deterministic/state_machine.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .base import DecisionPolicy, DecisionSource, Observation, PolicyState, Predicate, resolve_decision
from .types import Decision, PolicyResult


@dataclass(frozen=True)
class Transition:
    transition_id: str
    source: str  # a state name, or "*" for any state
    target: str
    guard: Predicate
    then: DecisionSource
    priority: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.transition_id.strip():
            raise ValueError("transition_id cannot be empty")
        if not self.source.strip() or not self.target.strip():
            raise ValueError("transition source and target cannot be empty")
        if not callable(self.guard):
            raise TypeError("transition guard must be callable")


class StateMachinePolicy(DecisionPolicy):
    """Select one transition for the current state using stable priority order.

    The chosen decision carries ``state_updates[state_field] = target``; the caller
    applies the updates. A guard that raises fails closed (REJECT, state unchanged).
    """

    def __init__(self, policy_id: str, transitions: list[Transition] | tuple[Transition, ...], *,
                 initial_state: str, state_field: str = "machine_state",
                 default: DecisionSource | None = None):
        super().__init__(policy_id)
        ids = [transition.transition_id for transition in transitions]
        if len(ids) != len(set(ids)):
            raise ValueError("transition_id values must be unique within a policy")
        self.transitions = tuple(sorted(transitions, key=lambda item: (-item.priority, item.transition_id)))
        self.initial_state = initial_state
        self.state_field = state_field
        self.default = default

    def current_state(self, state: PolicyState | None) -> str:
        return str((state or {}).get(self.state_field) or self.initial_state)

    def decide(self, observation: Observation, state: PolicyState | None = None) -> PolicyResult:
        observation = dict(observation)
        state = dict(state or {})
        current = self.current_state(state)
        trace = self._new_trace(observation, state)
        trace.add("current_state", "state", outcome=current)

        for transition in self.transitions:
            if transition.source not in (current, "*"):
                continue
            try:
                matched = bool(transition.guard(observation, state))
            except Exception as exc:
                decision = Decision.reject(
                    f"transition {transition.transition_id} failed closed: {type(exc).__name__}: {exc}"
                )
                decision.rule_id = transition.transition_id
                trace.add(transition.transition_id, "transition_error", outcome=False, detail=decision.reason)
                trace.finish(decision)
                return PolicyResult(decision, trace)

            trace.add(transition.transition_id, "transition_guard", outcome=matched,
                      detail=transition.description)
            if matched:
                decision = resolve_decision(transition.then, observation, state)
                updates = dict(decision.state_updates)
                updates[self.state_field] = transition.target
                decision = replace(decision, state_updates=updates,
                                   rule_id=decision.rule_id or transition.transition_id)
                trace.add(transition.transition_id, "transition_selected",
                          outcome=transition.target, detail=f"{current} -> {transition.target}")
                trace.finish(decision)
                return PolicyResult(decision, trace)

        if self.default is not None:
            decision = resolve_decision(self.default, observation, state)
        else:
            decision = Decision.pause(f"no transition matched state {current}")
        trace.add("no_transition", "default", outcome=current, detail=decision.reason)
        trace.finish(decision)
        return PolicyResult(decision, trace)

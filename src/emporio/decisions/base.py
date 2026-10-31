"""Base protocol for deterministic decision policies.

Adapted from JadeAgent (``jadeagent/deterministic/base.py``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any, Callable

from .types import Decision, DecisionTrace, PolicyResult, canonical_json_hash

Observation = dict[str, Any]
PolicyState = dict[str, Any]
Predicate = Callable[[Observation, PolicyState], bool]
DecisionFactory = Callable[[Observation, PolicyState], Decision]
DecisionSource = Decision | DecisionFactory


class DecisionPolicy(ABC):
    """Pure-policy contract: equal inputs are expected to produce equal outcomes."""

    def __init__(self, policy_id: str):
        if not str(policy_id).strip():
            raise ValueError("policy_id cannot be empty")
        self.policy_id = str(policy_id)

    @abstractmethod
    def decide(self, observation: Observation, state: PolicyState | None = None) -> PolicyResult:
        """Evaluate an observation without performing side effects."""

    def _new_trace(self, observation: Observation, state: PolicyState) -> DecisionTrace:
        return DecisionTrace(
            policy_id=self.policy_id,
            observation_hash=canonical_json_hash(observation),
            state_hash=canonical_json_hash(state),
        )


def resolve_decision(source: DecisionSource, observation: Observation, state: PolicyState) -> Decision:
    decision = source(observation, state) if callable(source) else source
    if not isinstance(decision, Decision):
        raise TypeError(f"decision source returned {type(decision).__name__}, expected Decision")
    # Copy so a shared Decision constant is never mutated by a caller.
    return replace(decision, state_updates=dict(decision.state_updates))

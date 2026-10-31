"""Deterministic, explainable decision primitives.

A trimmed port of the ``deterministic`` package from JadeAgent
(https://github.com/MadrasLe/JadeAgent), the author's agent runtime. Only the
pieces this project uses were kept: typed decisions, traces, ordered business
rules and guarded state machines.
"""

from .base import DecisionPolicy, Observation, PolicyState
from .rules import Rule, RulePolicy
from .state_machine import StateMachinePolicy, Transition
from .types import Decision, DecisionKind, DecisionTrace, PolicyResult

__all__ = [
    "Decision",
    "DecisionKind",
    "DecisionPolicy",
    "DecisionTrace",
    "Observation",
    "PolicyResult",
    "PolicyState",
    "Rule",
    "RulePolicy",
    "StateMachinePolicy",
    "Transition",
]

"""Ordered, deterministic business-rule policies.

Adapted from JadeAgent (``jadeagent/deterministic/rules.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .base import DecisionPolicy, DecisionSource, Observation, PolicyState, Predicate, resolve_decision
from .types import Decision, PolicyResult


@dataclass(frozen=True)
class Rule:
    rule_id: str
    when: Predicate
    then: DecisionSource
    priority: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id cannot be empty")
        if not callable(self.when):
            raise TypeError("rule predicate must be callable")


class RulePolicy(DecisionPolicy):
    """Evaluate rules by descending priority, then stable rule identifier.

    The first matching rule wins. A rule that raises fails closed (REJECT).
    """

    def __init__(self, policy_id: str, rules: list[Rule] | tuple[Rule, ...], *,
                 default: DecisionSource | None = None):
        super().__init__(policy_id)
        ids = [rule.rule_id for rule in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique within a policy")
        self.rules = tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.rule_id)))
        self.default = default or Decision.escalate("no deterministic rule matched")

    def decide(self, observation: Observation, state: PolicyState | None = None) -> PolicyResult:
        observation = dict(observation)
        state = dict(state or {})
        trace = self._new_trace(observation, state)

        for rule in self.rules:
            try:
                matched = bool(rule.when(observation, state))
            except Exception as exc:
                decision = Decision.reject(f"rule {rule.rule_id} failed closed: {type(exc).__name__}: {exc}")
                decision.rule_id = rule.rule_id
                trace.add(rule.rule_id, "rule_error", outcome=False, detail=decision.reason)
                trace.finish(decision)
                return PolicyResult(decision, trace)

            trace.add(rule.rule_id, "rule", outcome=matched, detail=rule.description)
            if matched:
                decision = resolve_decision(rule.then, observation, state)
                if not decision.rule_id:
                    decision = replace(decision, rule_id=rule.rule_id)
                trace.finish(decision)
                return PolicyResult(decision, trace)

        decision = resolve_decision(self.default, observation, state)
        trace.add("default", "default", outcome=True, detail="no rule matched")
        trace.finish(decision)
        return PolicyResult(decision, trace)

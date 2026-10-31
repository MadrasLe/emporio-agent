from emporio.decisions import Decision, DecisionKind, Rule, RulePolicy, StateMachinePolicy, Transition


def _policy() -> RulePolicy:
    return RulePolicy("demo", [
        Rule("low", lambda o, s: o["x"] > 0, Decision.finish("positive"), priority=1),
        Rule("high", lambda o, s: o["x"] > 10, Decision.finish("big"), priority=5),
    ])


def test_rules_are_evaluated_by_priority_and_first_match_wins():
    result = _policy().decide({"x": 50})
    assert result.decision.value == "big"
    assert result.decision.rule_id == "high"
    assert [step.step_id for step in result.trace.steps] == ["high"]


def test_rules_fall_back_to_default_escalation():
    result = _policy().decide({"x": -1})
    assert result.decision.kind == DecisionKind.ESCALATE


def test_rule_errors_fail_closed():
    policy = RulePolicy("boom", [Rule("bad", lambda o, s: o["missing"], Decision.finish(True))])
    result = policy.decide({})
    assert result.decision.kind == DecisionKind.REJECT
    assert result.decision.rule_id == "bad"


def test_trace_hash_is_stable_for_equal_inputs():
    assert _policy().decide({"x": 3}).trace.trace_hash == _policy().decide({"x": 3}).trace.trace_hash
    assert _policy().decide({"x": 3}).trace.trace_hash != _policy().decide({"x": 30}).trace.trace_hash


def test_explain_lists_checked_rules():
    explained = _policy().decide({"x": 3}).explain()
    assert explained["rule_id"] == "low"
    assert [item["rule"] for item in explained["checked"]] == ["high", "low"]


def test_state_machine_moves_and_reports_target():
    machine = StateMachinePolicy("door", [
        Transition("open", "closed", "opened", lambda o, s: o["push"], Decision.act("open_door")),
        Transition("lock", "*", "locked", lambda o, s: o.get("key"), Decision.act("lock"), priority=9),
    ], initial_state="closed", state_field="door")

    opened = machine.decide({"push": True}, {})
    assert opened.decision.state_updates == {"door": "opened"}

    locked = machine.decide({"push": False, "key": True}, {"door": "opened"})
    assert locked.decision.state_updates["door"] == "locked"

    idle = machine.decide({"push": False}, {"door": "opened"})
    assert idle.decision.kind == DecisionKind.WAIT

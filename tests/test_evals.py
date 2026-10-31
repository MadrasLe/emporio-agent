import yaml

from emporio.evals import EVALS_DIR, check_turn


def _tool(name: str, outcome: str = "action") -> dict:
    return {"type": "tool", "tool": name, "args": {}, "gate": {"outcome": outcome}}


def test_checks_are_accent_insensitive_and_support_alternatives():
    turn = {"must_include": ["indisponivel|sem estoque"], "must_not_include": ["Paris"]}
    checks = check_turn(turn, "Esse modelo está Indisponível no momento.", [])
    assert all(c["ok"] for c in checks)


def test_blocked_tool_calls_do_not_count_as_executed():
    turn = {"forbid_tools": ["get_orders"], "expect_tools": ["verify_customer|get_policy"]}
    audit = [_tool("get_orders", "reject"), _tool("get_policy")]
    assert all(c["ok"] for c in check_turn(turn, "ok", audit))


def test_safe_fallback_fails_the_turn():
    checks = check_turn({}, "x", [{"type": "constitution", "fallback": True}])
    assert not all(c["ok"] for c in checks)


def test_scenario_file_is_valid():
    scenarios = yaml.safe_load((EVALS_DIR / "scenarios.yaml").read_text(encoding="utf-8"))
    assert len({s["id"] for s in scenarios}) == len(scenarios)
    examples = sorted(s["example"] for s in scenarios if s.get("example"))
    assert examples == list(range(1, len(examples) + 1)) and 3 <= len(examples) <= 5

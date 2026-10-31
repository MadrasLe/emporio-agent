from emporio.decisions import DecisionKind
from emporio.domain.orders import (
    ANON,
    IDENTITY_FIELD,
    LOCKED,
    VERIFIED,
    IdentityClaim,
    check_return,
    order_view,
    verify_identity,
)

# order 7 belongs to customer 14 (Letícia, leticia.rocha@jmail.com, (67) 99789-0123)


def _apply(state: dict, result) -> dict:
    return {**state, **result.decision.state_updates}


def test_identity_needs_two_factors(data):
    result = verify_identity(data, IdentityClaim(order_id=7), {})
    assert result.decision.kind == DecisionKind.WAIT
    assert IDENTITY_FIELD not in result.decision.state_updates or result.decision.state_updates[IDENTITY_FIELD] == ANON


def test_identity_with_order_and_email_or_phone(data):
    by_email = verify_identity(data, IdentityClaim(order_id=7, email="Leticia.Rocha@jmail.com "), {})
    assert by_email.decision.state_updates == {IDENTITY_FIELD: VERIFIED, "customer_id": 14, "failed_attempts": 0}
    by_phone = verify_identity(data, IdentityClaim(order_id=7, phone="99789-0123"), {})
    assert by_phone.decision.state_updates["customer_id"] == 14


def test_shared_email_is_disambiguated_by_phone(data):
    shared = [c for c in data.customers.values() if c.email == "bruno.martins@jmail.com"]
    assert len(shared) == 2
    for customer in shared:
        result = verify_identity(data, IdentityClaim(email=customer.email, phone=customer.phone), {})
        assert result.decision.state_updates["customer_id"] == customer.id


def test_three_failures_lock_identity(data):
    state: dict = {}
    wrong = IdentityClaim(order_id=7, email="someone@else.com")
    for expected in (ANON, ANON, LOCKED):
        state = _apply(state, verify_identity(data, wrong, state))
        assert state[IDENTITY_FIELD] == expected
    right = IdentityClaim(order_id=7, email="leticia.rocha@jmail.com")
    locked = verify_identity(data, right, state)
    assert locked.decision.kind == DecisionKind.ESCALATE
    assert locked.decision.state_updates[IDENTITY_FIELD] == LOCKED


def test_regret_window_expired_but_legal_warranty_valid(data, today):
    order = data.orders[7]  # delivered, bought 03/02, estimated delivery 17/02
    regret = check_return(order, "arrependimento", today)
    assert regret.decision.rule_id == "RET_REGRET_EXPIRED"
    assert "24/02/2026" in regret.decision.reason
    defect = check_return(order, "defeito", today)
    assert defect.decision.rule_id == "RET_DEFECT_LEGAL"
    assert defect.decision.value["elegivel"] is True


def test_regret_within_seven_days(data):
    from datetime import date
    result = check_return(data.orders[7], "arrependimento", date(2026, 2, 20))
    assert result.decision.rule_id == "RET_REGRET_OK"
    assert any("10 dias úteis" in c for c in result.decision.value["condicoes"])


def test_return_paths_for_orders_not_delivered(data, today):
    assert check_return(data.orders[8], "arrependimento", today).decision.rule_id == "RET_IN_TRANSIT"
    assert check_return(data.orders[12], "defeito", today).decision.kind == DecisionKind.ESCALATE
    assert check_return(data.orders[17], "arrependimento", today).decision.rule_id == "RET_CANCELLED"


def test_defect_after_legal_warranty(data, today):
    result = check_return(data.orders[1], "defeito", today)  # delivered Oct/2025
    assert result.decision.rule_id == "RET_DEFECT_MANUFACTURER"


def test_order_view_flags_late_delivery(data, today):
    view = order_view(data, data.orders[8], today)
    assert view["status"].startswith("enviado")
    assert view["codigo_rastreio"] == "BRJL5544332BR"
    assert any("ATRASADO" in alert for alert in view["alertas"])

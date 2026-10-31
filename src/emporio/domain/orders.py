"""Customer identity verification, order status and return/exchange eligibility.

Identity uses a state machine (LGPD: order data is only shown to its owner).
Return eligibility uses ordered business rules from manual sections 4 and 8.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..data.loader import Customer, Order, StoreData
from ..decisions import Decision, PolicyResult, Rule, RulePolicy, StateMachinePolicy, Transition
from .money import brl

# --- identity -------------------------------------------------------------------

ANON, VERIFIED, LOCKED = "anon", "verified", "locked"
IDENTITY_FIELD = "identity_state"
MAX_FAILED_ATTEMPTS = 3


def digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def phones_match(given: str, stored: str) -> bool:
    """Accept the number with or without country/area code (at least 8 digits)."""

    a, b = digits(given), digits(stored)
    return len(a) >= 8 and len(b) >= 8 and (a.endswith(b) or b.endswith(a))


@dataclass(frozen=True)
class IdentityClaim:
    order_id: int | None = None
    email: str | None = None
    phone: str | None = None

    @property
    def factors(self) -> int:
        return sum(1 for value in (self.order_id, self.email, self.phone) if value)


def match_customer(data: StoreData, claim: IdentityClaim) -> Customer | None:
    """The customer that every provided identifier points to, or None."""

    if claim.order_id is not None:
        order = data.orders.get(claim.order_id)
        candidates = [data.customers[order.customer_id]] if order else []
    elif claim.email:
        candidates = [c for c in data.customers.values() if c.email == claim.email.strip().lower()]
    else:
        return None
    for customer in candidates:
        if claim.email and customer.email != claim.email.strip().lower():
            continue
        if claim.phone and not phones_match(claim.phone, customer.phone):
            continue
        return customer
    return None


def _attempts(state: dict) -> int:
    return int(state.get("failed_attempts", 0))


def _identity_transitions() -> list[Transition]:
    transitions = [
        Transition("ID_LOCKED", LOCKED, LOCKED, lambda o, s: True,
                   Decision.escalate("verificação bloqueada após 3 tentativas: encaminhar para atendente humano"),
                   priority=100, description="identidade bloqueada permanece bloqueada"),
    ]
    for source in (ANON, VERIFIED):
        transitions += [
            Transition(f"ID_INSUFFICIENT_{source}", source, source, lambda o, s: o["factors"] < 2,
                       Decision.pause("preciso de 2 dados: número do pedido + e-mail ou telefone "
                                      "(ou e-mail + telefone)"),
                       priority=90, description="exige 2 fatores de identificação"),
            Transition(f"ID_MATCH_{source}", source, VERIFIED, lambda o, s: o["customer_id"] is not None,
                       lambda o, s: Decision.act("grant_access", reason="dados conferem com o cadastro",
                                                 state_updates={"customer_id": o["customer_id"],
                                                                "failed_attempts": 0}),
                       priority=50, description="todos os dados informados pertencem ao mesmo cliente"),
            Transition(f"ID_FAIL_LOCK_{source}", source, LOCKED,
                       lambda o, s: _attempts(s) + 1 >= MAX_FAILED_ATTEMPTS,
                       lambda o, s: Decision.escalate(
                           "dados não conferem pela 3ª vez: bloquear e encaminhar para atendente humano",
                           state_updates={"failed_attempts": _attempts(s) + 1, "customer_id": None}),
                       priority=40, description=f"{MAX_FAILED_ATTEMPTS} falhas bloqueiam a verificação"),
            Transition(f"ID_FAIL_{source}", source, source, lambda o, s: True,
                       lambda o, s: Decision.reject(
                           "os dados informados não conferem com nenhum pedido/cadastro",
                           state_updates={"failed_attempts": _attempts(s) + 1}),
                       priority=0, description="dados não conferem"),
        ]
    return transitions


IDENTITY_MACHINE = StateMachinePolicy("identity", _identity_transitions(), initial_state=ANON,
                                      state_field=IDENTITY_FIELD)


def verify_identity(data: StoreData, claim: IdentityClaim, state: dict) -> PolicyResult:
    customer = match_customer(data, claim) if claim.factors >= 2 else None
    observation = {"factors": claim.factors, "customer_id": customer.id if customer else None}
    return IDENTITY_MACHINE.decide(observation, state)


# --- order status ---------------------------------------------------------------

ORDER_STATUS_LABEL = {
    "pending": "aguardando confirmação do pagamento",
    "confirmed": "pagamento confirmado, pedido em separação",
    "shipped": "enviado (em transporte)",
    "delivered": "entregue",
    "cancelled": "cancelado",
}
STALE_AFTER_DAYS = 7


def payment_label(order: Order) -> str:
    if order.payment_method.startswith("credit"):
        return f"cartão de crédito em {order.installments}x"
    return {"pix": "PIX", "debit": "cartão de débito", "boleto": "boleto bancário"}.get(
        order.payment_method, order.payment_method)


def order_alerts(order: Order, today: date) -> list[str]:
    alerts = []
    if order.status == "shipped" and order.estimated_delivery and today > order.estimated_delivery:
        late = (today - order.estimated_delivery).days
        alerts.append(f"ATRASADO: previsão de entrega era {order.estimated_delivery:%d/%m/%Y} "
                      f"({late} dias atrás). Oferecer abrir chamado de reclamação (retorno em até 24h úteis).")
    if order.status in ("pending", "confirmed") and (today - order.order_date).days > STALE_AFTER_DAYS:
        alerts.append(f"Pedido parado em '{ORDER_STATUS_LABEL[order.status]}' há "
                      f"{(today - order.order_date).days} dias. Oferecer encaminhar para a equipe verificar.")
    return alerts


def order_view(data: StoreData, order: Order, today: date) -> dict:
    view = {
        "pedido": order.id,
        "data_do_pedido": f"{order.order_date:%d/%m/%Y}",
        "status": ORDER_STATUS_LABEL[order.status],
        "itens": [
            {"produto": data.products[item.product_id].name if item.product_id in data.products
             else f"produto #{item.product_id}", "quantidade": item.quantity}
            for item in order.items
        ],
        "total": brl(order.total),
        "pagamento": payment_label(order),
    }
    if order.tracking_code:
        view["codigo_rastreio"] = order.tracking_code
    if order.estimated_delivery:
        view["previsao_entrega"] = f"{order.estimated_delivery:%d/%m/%Y}"
    if order.notes:
        view["observacao"] = order.notes
    if alerts := order_alerts(order, today):
        view["alertas"] = alerts
    return view


# --- returns, exchanges and warranty (manual 4 and 8) ---------------------------

REASONS = ("arrependimento", "defeito", "preferencia")
REGRET_DAYS = 7
PREFERENCE_DAYS = 7
DEFECT_EXCHANGE_DAYS = 30
LEGAL_WARRANTY_DAYS = 90

_COMMON_CONDITIONS = [
    "não vale para instrumentos personalizados/com ajuste sob encomenda, itens de 'venda final' "
    "e boquilhas de sopro (manual 4.4)",
]


def received_date(order: Order) -> date | None:
    """The data has no real delivery date; the estimated date is used as proxy (README)."""

    if order.status != "delivered":
        return None
    return order.estimated_delivery or order.order_date


def _eligible(path: str, deadline: str, conditions: list[str]) -> Decision:
    return Decision.finish({"elegivel": True, "caminho": path, "prazo": deadline,
                            "condicoes": conditions + _COMMON_CONDITIONS},
                           reason=f"{path}: dentro do prazo ({deadline})")


def _not_eligible(reason: str, hint: str) -> Decision:
    return Decision.reject(reason, value={"elegivel": False, "sugestao": hint})


def _regret_ok(o: dict, s: dict) -> Decision:
    return _eligible(
        "devolução por arrependimento (direito de arrependimento)",
        f"até {o['regret_deadline']:%d/%m/%Y} (7 dias corridos após o recebimento)",
        ["produto na embalagem original, sem sinais de uso, com acessórios e manuais",
         "reembolso na mesma forma de pagamento em até 10 dias úteis",
         "frete de devolução por conta da loja"],
    )


def _preference_ok(o: dict, s: dict) -> Decision:
    return _eligible(
        "troca por preferência (cor, modelo, tamanho)",
        f"até {o['preference_deadline']:%d/%m/%Y} (7 dias)",
        ["sujeita à disponibilidade do produto desejado",
         "produto em perfeito estado e na embalagem original",
         "diferença de valor cobrada ou reembolsada"],
    )


def _defect_store(o: dict, s: dict) -> Decision:
    return _eligible(
        "troca por defeito de fabricação direto com a loja",
        f"até {o['defect_deadline']:%d/%m/%Y} (30 dias corridos após a compra)",
        ["danos por mau uso, queda, umidade excessiva ou modificações não são cobertos"],
    )


def _defect_legal(o: dict, s: dict) -> Decision:
    return _eligible(
        "garantia legal (CDC): após 30 dias a garantia é acionada com o fabricante, "
        "e a Empório pode intermediar o processo",
        f"até {o['legal_deadline']:%d/%m/%Y} (90 dias após o recebimento)",
        ["desgaste natural, mau uso, queda e reparos por terceiros não são cobertos"],
    )


RETURN_POLICY = RulePolicy("returns", [
    Rule("RET_REASON_UNKNOWN", lambda o, s: o["reason"] not in REASONS,
         lambda o, s: Decision.reject(f"motivo deve ser um de: {', '.join(REASONS)}"), priority=100,
         description="motivo reconhecido"),
    Rule("RET_CANCELLED", lambda o, s: o["status"] == "cancelled",
         _not_eligible("o pedido foi cancelado, não há produto a devolver", "nenhuma ação necessária"),
         priority=90, description="pedido cancelado"),
    Rule("RET_NOT_SHIPPED", lambda o, s: o["status"] in ("pending", "confirmed"),
         Decision.escalate("o pedido ainda não foi enviado: o caminho é o cancelamento, feito pela equipe",
                           value={"elegivel": False, "sugestao": "abrir chamado de cancelamento"}),
         priority=80, description="pedido ainda não enviado"),
    Rule("RET_IN_TRANSIT", lambda o, s: o["status"] == "shipped",
         Decision.pause("o pedido ainda está em transporte: os prazos contam a partir do recebimento",
                        value={"elegivel": False, "sugestao": "se chegar avariado, recusar o recebimento e "
                                                              "contatar a loja imediatamente"}),
         priority=80, description="pedido em transporte"),
    Rule("RET_REGRET_OK", lambda o, s: o["reason"] == "arrependimento" and o["days_since_receipt"] <= REGRET_DAYS,
         _regret_ok, priority=50, description="arrependimento: até 7 dias corridos após o recebimento"),
    Rule("RET_REGRET_EXPIRED", lambda o, s: o["reason"] == "arrependimento",
         lambda o, s: _not_eligible(
             f"o prazo de arrependimento (7 dias após o recebimento) terminou em {o['regret_deadline']:%d/%m/%Y}",
             "se houver defeito de fabricação, verificar troca por defeito ou garantia"),
         priority=49, description="arrependimento fora do prazo"),
    Rule("RET_PREF_OK", lambda o, s: o["reason"] == "preferencia" and o["days_since_receipt"] <= PREFERENCE_DAYS,
         _preference_ok, priority=40, description="preferência: até 7 dias"),
    Rule("RET_PREF_EXPIRED", lambda o, s: o["reason"] == "preferencia",
         lambda o, s: _not_eligible(
             f"o prazo de troca por preferência (7 dias) terminou em {o['preference_deadline']:%d/%m/%Y}",
             "se houver defeito de fabricação, verificar troca por defeito ou garantia"),
         priority=39, description="preferência fora do prazo"),
    Rule("RET_DEFECT_STORE", lambda o, s: o["reason"] == "defeito" and o["days_since_purchase"] <= DEFECT_EXCHANGE_DAYS,
         _defect_store, priority=30, description="defeito: troca na loja até 30 dias após a compra"),
    Rule("RET_DEFECT_LEGAL", lambda o, s: o["reason"] == "defeito" and o["days_since_receipt"] <= LEGAL_WARRANTY_DAYS,
         _defect_legal, priority=29, description="defeito: garantia legal de 90 dias após o recebimento"),
    Rule("RET_DEFECT_MANUFACTURER", lambda o, s: o["reason"] == "defeito",
         lambda o, s: _not_eligible(
             f"a garantia legal de 90 dias terminou em {o['legal_deadline']:%d/%m/%Y}",
             "verificar a garantia do fabricante (6 meses a 2 anos, conforme certificado); "
             "a Empório pode intermediar"),
         priority=28, description="defeito após a garantia legal"),
])


def check_return(order: Order, reason: str, today: date) -> PolicyResult:
    received = received_date(order)
    observation = {
        "status": order.status,
        "reason": reason,
        "days_since_purchase": (today - order.order_date).days,
        "defect_deadline": order.order_date + timedelta(days=DEFECT_EXCHANGE_DAYS),
    }
    if received:
        observation.update({
            "days_since_receipt": (today - received).days,
            "regret_deadline": received + timedelta(days=REGRET_DAYS),
            "preference_deadline": received + timedelta(days=PREFERENCE_DAYS),
            "legal_deadline": received + timedelta(days=LEGAL_WARRANTY_DAYS),
        })
    return RETURN_POLICY.decide(observation)

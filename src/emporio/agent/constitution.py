"""The assistant's constitution, enforced in code (see knowledge/constitution.md).

Two layers, both deterministic:

* **Tool gate** (before a tool runs): a ``RulePolicy`` in the spirit of
  JadeAgent's ``evaluate_tool_call`` — known tools only, identity before order
  data (C3), order ownership (C3), write budget.
* **Answer validators** (after the LLM writes): money grounding (C1), promotion
  transparency (C2), privacy (C4) and unsupported offers (C6). A failing answer
  is revised once.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..data.loader import StoreData
from ..decisions import Decision, PolicyResult, Rule, RulePolicy
from ..domain.money import brl, find_brl_amounts, number_values
from ..domain.orders import ANON, LOCKED, VERIFIED, phones_match
from ..domain.pricing import active_promotion, quote
from .tools import ToolSpec

IDENTITY_TOOLS = {"verify_customer", "get_orders", "check_return"}
MAX_TICKETS_PER_CONVERSATION = 3

TOOL_GATE = RulePolicy("tool_gate", [
    Rule("G_UNKNOWN_TOOL", lambda o, s: not o["known"],
         lambda o, s: Decision.reject(f"a ferramenta '{o['tool']}' não existe"),
         priority=100, description="só ferramentas registradas"),
    Rule("G_IDENTITY_LOCKED", lambda o, s: o["identity_tool"] and o["identity_state"] == LOCKED,
         Decision.reject("C3: a verificação de identidade foi bloqueada após 3 tentativas; "
                         "ofereça atendimento humano com open_ticket"),
         priority=90, description="identidade bloqueada"),
    Rule("G_IDENTITY_REQUIRED", lambda o, s: o["requires_identity"] and o["identity_state"] != VERIFIED,
         Decision.reject("C3: confirme a identidade com verify_customer antes (número do pedido + e-mail "
                         "ou telefone)"),
         priority=80, description="dados de pedido só com identidade verificada"),
    Rule("G_ORDER_OWNERSHIP", lambda o, s: o["order_owned"] is False,
         Decision.reject("C3: esse pedido não aparece no cadastro do cliente verificado; não confirme nem "
                         "negue que ele exista e peça para o cliente conferir o número"),
         priority=70, description="pedido pertence ao cliente verificado"),
    Rule("G_WRITE_BUDGET", lambda o, s: o["writes"] and o["writes_so_far"] >= MAX_TICKETS_PER_CONVERSATION,
         Decision.reject("limite de chamados desta conversa atingido; informe os protocolos já abertos"),
         priority=60, description=f"no máximo {MAX_TICKETS_PER_CONVERSATION} chamados por conversa"),
    Rule("G_ALLOW", lambda o, s: True, Decision.act("execute", reason="permitido pela constituição"),
         priority=0, description="demais casos"),
])


def evaluate_tool_call(spec: ToolSpec | None, name: str, args: dict, state: dict, data: StoreData) -> PolicyResult:
    order_owned = None
    if spec is not None and spec.requires_identity and args.get("order_id") is not None:
        try:
            order = data.orders.get(int(args["order_id"]))
        except (TypeError, ValueError):
            order = None
        order_owned = bool(order and order.customer_id == state.get("customer_id"))
    observation = {
        "tool": name,
        "known": spec is not None,
        "requires_identity": bool(spec and spec.requires_identity),
        "identity_tool": name in IDENTITY_TOOLS,
        "identity_state": state.get("identity_state") or ANON,
        "writes": bool(spec and "write" in spec.effects),
        "writes_so_far": len(state.get("tickets") or []),
        "order_owned": order_owned,
    }
    return TOOL_GATE.decide(observation)


# --- answer validators ----------------------------------------------------------------

IDENTIFIER_RE = re.compile(r"\bEM-\d{8}-[A-Z0-9]{4}\b|\bBR[A-Z0-9]{9}BR\b")  # ticket protocol, tracking code
STORE_EMAILS = {"contato@emporiodamusica.com.br", "contato@empóriodamusica.com.br"}
STORE_PHONES = ("(67) 3341-4444", "(67) 3321-4500")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# "(67) 99654-7821", "99654 7821", "67996547821" — but not digits glued to letters or hyphens,
# like the date inside a ticket protocol "EM-20260325-CB7B".
PHONE_RE = re.compile(
    r"(?<![\w-])(?:\(?\d{2}\)?\s*)?\d{4,5}[-\s]\d{4}(?![\w-])"
    r"|(?<![\w-])\d{10,11}(?![\w-])"
)


@dataclass(frozen=True)
class Violation:
    principle: str
    message: str

    def to_dict(self) -> dict:
        return {"principle": self.principle, "message": self.message}


def check_answer(answer: str, *, evidence: str, customer_text: str, data: StoreData,
                 verified_customer_id: int | None) -> list[Violation]:
    if not answer.strip():
        return [Violation("EMPTY", "a resposta ao cliente está vazia")]

    violations: list[Violation] = []
    mentioned = find_brl_amounts(answer)
    answer_values = {value for _, values in mentioned for value in values}

    # C1: every R$ amount must come from a tool result or from the customer's own words
    # (the customer may write "até 1000" without "R$").
    grounded = {value for _, values in find_brl_amounts(evidence) for value in values}
    grounded |= {value for raw in re.findall(r"\d[\d.,]*\d|\d", customer_text) for value in number_values(raw)}
    for raw, values in mentioned:
        if not values & grounded:
            violations.append(Violation("C1", f"o valor {raw} não veio de nenhuma ferramenta"))
    # ...and so must ticket protocols and tracking codes (an invented protocol is worse than none).
    for code in set(IDENTIFIER_RE.findall(answer)):
        if code not in evidence:
            violations.append(Violation("C1", f"o código {code} não veio de nenhuma ferramenta"))

    # C2: a promotional price is always shown with the original price and the discount.
    for product in data.products.values():
        promo = active_promotion(data, product.id)
        if not promo:
            continue
        q = quote(data, product)
        if q.price in answer_values:
            pct = f"{promo.discount_percent.normalize():f}"
            if q.list_price not in answer_values or not re.search(rf"\b{re.escape(pct)}\s*%", answer):
                violations.append(Violation(
                    "C2", f"{product.name}: o preço promocional {brl(q.price)} precisa vir junto do preço "
                          f"original {brl(q.list_price)} e do desconto de {pct}%"))

    # C4: no personal data of anyone but the verified customer (or what the customer typed).
    verified = data.customers.get(verified_customer_id) if verified_customer_id is not None else None
    typed = customer_text.lower()
    for email in {e.lower() for e in EMAIL_RE.findall(answer)}:
        if email not in STORE_EMAILS and email not in typed and not (verified and email == verified.email):
            violations.append(Violation("C4", f"o e-mail {email} não pode ser informado"))
    allowed_phones = [*STORE_PHONES, *([verified.phone] if verified else [])]
    for match in PHONE_RE.finditer(answer):
        phone = match.group(0)
        if not any(phones_match(phone, allowed) for allowed in allowed_phones) and \
                re.sub(r"\D", "", phone) not in re.sub(r"\D", "", customer_text):
            violations.append(Violation("C4", f"o telefone {phone} não pode ser informado"))
    lowered = answer.lower()
    for customer in data.customers.values():
        name = customer.name.lower()
        if customer.id != verified_customer_id and name in lowered and name not in typed:
            violations.append(Violation("C4", "a resposta cita o nome completo de outro cliente"))

    # C6: no offers to do what only the team can do (reserve, close a sale, process payments).
    if offer := UNSUPPORTED_OFFER_RE.search(_plain(answer)):
        violations.append(Violation(
            "C6", f"ofereceu algo que a assistente não faz ('{offer.group(0)}'): ela não reserva, separa, fecha "
                  "venda nem processa pagamentos; para comprar, o cliente finaliza com a equipe pelo WhatsApp "
                  "ou na loja"))

    unique: dict[tuple[str, str], Violation] = {(v.principle, v.message): v for v in violations}
    return list(unique.values())


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


# "quer que eu reserve", "posso separar um pra você", "vou fechar seu pedido" — but not "não posso reservar".
UNSUPPORTED_OFFER_RE = re.compile(
    r"(?<!nao )\b(?:quer que eu|gostaria que eu|deseja que eu|posso|vou|ja)\b[^.?!\n]{0,40}?"
    r"\b(?:reserv\w*|separ[aeo]\w*|finaliz\w*|fech(?:ar|o|e|amos)\b|process(?:ar|o|e|amos)\b)"
)


def critique_message(violations: list[Violation]) -> str:
    lines = "\n".join(f"- {v.principle}: {v.message}" for v in violations)
    return (
        "[Verificação automática da constituição — mensagem interna, não mostre ao cliente]\n"
        f"Sua última resposta foi bloqueada:\n{lines}\n"
        "Reescreva a resposta ao cliente corrigindo esses pontos. Use só valores que aparecem nos resultados das "
        "ferramentas (chame uma ferramenta se precisar). Não faça contas de cabeça. Responda apenas com o texto "
        "final para o cliente."
    )


FALLBACK_ANSWER = (
    "Quero te passar essa informação certinha, então prefiro confirmar com a equipe antes de responder. "
    "Se quiser, eu abro um chamado e eles te retornam em até 24 horas úteis. Pode ser?"
)

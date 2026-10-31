"""System prompt: persona + constitution + policy index + live context (rebuilt every turn)."""

from __future__ import annotations

from datetime import datetime

from ..data.loader import StoreData
from ..domain.orders import LOCKED, VERIFIED
from ..domain.store import store_status
from ..knowledge import KnowledgeBase


def _identity_line(state: dict, data: StoreData) -> str:
    identity = state.get("identity_state")
    if identity == VERIFIED and state.get("customer_id") in data.customers:
        customer = data.customers[state["customer_id"]]
        return (f"verificado — {customer.name.split()[0]} (pode consultar os pedidos dele/dela com get_orders "
                "e check_return)")
    if identity == LOCKED:
        return "verificação BLOQUEADA após 3 tentativas — só atendimento humano (open_ticket) para pedidos"
    return "não verificado (para assuntos de pedido, use verify_customer primeiro)"


def _catalog_line(data: StoreData) -> str:
    parts = []
    for category in data.categories.values():
        count = len(data.products_in(category.id))
        parts.append(f"{category.name} ({count} itens)" if count else f"{category.name} (SEM produtos no momento)")
    return "; ".join(parts)


def build_system_prompt(knowledge: KnowledgeBase, data: StoreData, now: datetime, state: dict) -> str:
    status = store_status(now)
    store_line = f"ABERTA (hoje: {status['horario_hoje']})" if status["loja_aberta"] else \
        f"FECHADA (hoje: {status['horario_hoje']}; a equipe volta {status['proxima_abertura']})"
    tickets = state.get("tickets") or []
    return f"""{knowledge.persona}

{knowledge.constitution}

## Políticas da loja (carregue com `get_policy` antes de responder sobre elas)
{knowledge.policy_index()}

## Contexto desta conversa
- Agora: {status['agora']} (horário de Campo Grande/MS). Loja {store_line}.
- Catálogo por categoria: {_catalog_line(data)}.
- Cliente: {_identity_line(state, data)}.
- Chamados abertos nesta conversa: {", ".join(tickets) if tickets else "nenhum"}.
"""

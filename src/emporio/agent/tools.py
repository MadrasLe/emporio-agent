"""Tools the LLM can call.

Each tool is thin: validate arguments, call the domain, return compact JSON in
Portuguese (the LLM relays it to the customer). Access control is not done
here; it lives in the constitution gate (``constitution.py``).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from ..data.loader import Product, StoreData
from ..decisions import DecisionKind
from ..domain.catalog import (
    AVAILABILITY_LABEL,
    Availability,
    alternatives,
    availability,
    description_brand_conflict,
    lookup,
    search,
)
from ..domain.money import brl, to_money
from ..domain.orders import (
    MAX_FAILED_ATTEMPTS,
    REASONS,
    IdentityClaim,
    check_return,
    order_view,
    verify_identity,
)
from ..domain.pricing import (
    PAYMENT_COMBINATION_MIN,
    check_installments,
    installment_value,
    max_installments,
    quote,
    quote_cart,
)
from ..domain.store import local_shipping_fee, shipping_quote, store_status
from ..knowledge import KnowledgeBase


@dataclass
class ToolContext:
    data: StoreData
    knowledge: KnowledgeBase
    now: datetime
    state: dict  # identity_state, customer_id, failed_attempts, tickets
    tickets_path: Path


@dataclass
class ToolOutcome:
    content: dict
    state_updates: dict = field(default_factory=dict)
    decision: dict | None = None  # PolicyResult.explain() when a business rule decided


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[Any, ToolContext], ToolOutcome]
    effects: tuple[str, ...] = ("read",)
    requires_identity: bool = False
    schema_overrides: dict = field(default_factory=dict)

    def openai_schema(self) -> dict:
        parameters = _strip_titles(self.args.model_json_schema())
        for prop, override in self.schema_overrides.items():
            parameters["properties"][prop].update(override)
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": parameters}}


def _strip_titles(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _strip_titles(v) for k, v in schema.items() if k != "title"}
    if isinstance(schema, list):
        return [_strip_titles(item) for item in schema]
    return schema


def to_json(content: dict) -> str:
    return json.dumps(content, ensure_ascii=False, default=str)


# --- helpers ----------------------------------------------------------------------

def _product_line(data: StoreData, product: Product) -> dict:
    q = quote(data, product)
    line = {"id": product.id, "nome": product.name, "preco": brl(q.price) + " (cartão ou boleto)",
            "disponibilidade": AVAILABILITY_LABEL[availability(product)]}
    if q.pix_price is not None:
        line["preco_pix"] = brl(q.pix_price)
    if q.promotion:
        line["promocao"] = (f"{q.promotion.discount_percent}% off ({q.promotion.description}): "
                            f"de {brl(q.list_price)} por {brl(q.price)}")
    return line


def _installment_request(amount: Decimal, installments: int) -> dict:
    result = check_installments(amount, installments)
    return {"permitido": result.decision.allowed, "motivo": result.decision.reason,
            "regra": result.decision.rule_id}


def _not_found(text: str, candidates: list[Product], data: StoreData) -> dict:
    if candidates:
        return {"encontrado": False, "ambiguo": True, "termo": text,
                "opcoes": [_product_line(data, p) for p in candidates],
                "instrucao": "pergunte ao cliente qual destes ele quer"}
    return {"encontrado": False, "termo": text,
            "instrucao": "não existe produto com esse nome; use search_products para sugerir opções"}


# --- catalog ----------------------------------------------------------------------

class SearchProductsArgs(BaseModel):
    query: str = Field("", description="palavras do cliente que descrevem o que ele quer: estilo, uso ou "
                                       "característica (ex.: 'choro', 'rock', 'iniciante', 'nylon elétrico', "
                                       "'tenor', '7 cordas'). Sempre preencha quando o cliente descrever algo: "
                                       "os resultados vêm ordenados por relevância (BM25)")
    category: str = Field("", description="categoria do catálogo, ex.: 'violões', 'guitarras', 'ukuleles'")
    min_price: float | None = Field(None, description="preço mínimo em reais")
    max_price: float | None = Field(None, description="preço máximo em reais")
    include_unavailable: bool = Field(False, description="incluir itens sem estoque, fora de linha ou em breve")


def search_products(args: SearchProductsArgs, ctx: ToolContext) -> ToolOutcome:
    data = ctx.data
    result = search(data, query=args.query, category=args.category,
                    min_price=to_money(args.min_price) if args.min_price is not None else None,
                    max_price=to_money(args.max_price) if args.max_price is not None else None,
                    include_unavailable=args.include_unavailable)
    if result.unknown_category:
        return ToolOutcome({"erro": f"a loja não tem a categoria '{result.unknown_category}'",
                            "categorias_da_loja": [c.name for c in data.categories.values()]})
    content: dict = {"filtros": args.model_dump(exclude_defaults=True),
                     "total_encontrado": len(result.products),
                     "produtos": [_product_line(data, p) for p in result.products]}
    if result.category:
        content["categoria"] = result.category.name + (" (deduzida do texto)" if result.category_inferred else "")
        if not data.products_in(result.category.id):
            content["observacao"] = (f"a categoria {result.category.name} não tem nenhum produto no catálogo "
                                     "no momento; não invente itens, ofereça encaminhar o interesse à equipe")
    if result.text_matched:
        content["ordem"] = "por relevância para os termos buscados"
    elif result.text_matched is False and result.products:
        content["relevancia"] = "nenhum item cita esses termos; segue a categoria inteira por preço"
    if not result.products and args.max_price is not None:
        closest = search(data, query=args.query, category=args.category, limit=3).products
        content["mais_baratos_disponiveis"] = [_product_line(data, p) for p in closest]
    content["preco_considerado"] = "preço final (já com promoção ativa, quando houver)"
    return ToolOutcome(content)


class GetProductArgs(BaseModel):
    product: str = Field(..., description="nome (pode ser aproximado) ou id do produto")
    installments: int | None = Field(None, description="número de parcelas que o cliente perguntou, se perguntou")


def get_product(args: GetProductArgs, ctx: ToolContext) -> ToolOutcome:
    data = ctx.data
    found = lookup(data, args.product)
    if not found.product:
        return ToolOutcome(_not_found(args.product, found.candidates, data))

    p = found.product
    status = availability(p)
    content: dict = {
        "encontrado": True, "id": p.id, "nome": p.name,
        "categoria": data.categories[p.category_id].name if p.category_id in data.categories else None,
        "descricao": p.description, "especificacoes": p.specs,
        "disponibilidade": AVAILABILITY_LABEL[status],
    }
    if conflict := description_brand_conflict(p):
        content["atencao_dados"] = (f"a descrição cadastrada cita outra marca ({', '.join(sorted(conflict))}); "
                                    "use só o nome do produto e não afirme marca/modelo da descrição sem "
                                    "confirmar com a equipe")
    if status in (Availability.AVAILABLE, Availability.OUT_OF_STOCK):
        q = quote(data, p)
        content["precos"] = q.to_dict()
        if status == Availability.AVAILABLE:
            content["unidades_em_estoque"] = p.stock
        if args.installments:
            content["parcelamento_solicitado"] = _installment_request(q.price, args.installments)
    else:
        content["observacao"] = "produto não está à venda; não informe preço"
    if status != Availability.AVAILABLE:
        content["alternativas_disponiveis"] = [_product_line(data, a) for a in alternatives(data, p)]
    return ToolOutcome(content)


class OrderItemArg(BaseModel):
    product: str = Field(..., description="nome ou id do produto")
    quantity: int = Field(1, ge=1, le=20)


class QuoteOrderArgs(BaseModel):
    items: list[OrderItemArg] = Field(..., min_length=1, description="itens do orçamento")
    city: str | None = Field(None, description="cidade de entrega, se o cliente informou")
    installments: int | None = Field(None, description="parcelas que o cliente perguntou, se perguntou")


def quote_order(args: QuoteOrderArgs, ctx: ToolContext) -> ToolOutcome:
    data = ctx.data
    resolved: list[tuple[Product, int]] = []
    problems: list[dict] = []
    for item in args.items:
        found = lookup(data, item.product)
        if not found.product:
            problems.append(_not_found(item.product, found.candidates, data))
        elif availability(found.product) != Availability.AVAILABLE:
            problems.append({"produto": found.product.name,
                             "problema": AVAILABILITY_LABEL[availability(found.product)],
                             "alternativas_disponiveis": [_product_line(data, a)
                                                          for a in alternatives(data, found.product)]})
        elif item.quantity > found.product.stock:
            problems.append({"produto": found.product.name,
                             "problema": f"só há {found.product.stock} unidade(s) em estoque"})
        else:
            resolved.append((found.product, item.quantity))
    if not resolved:
        return ToolOutcome({"orcamento": None, "problemas": problems})

    cart = quote_cart(data, resolved)
    n = max_installments(cart.total)
    content: dict = {
        "itens": [
            {"produto": line.product.name, "quantidade": line.quantity, "preco_unitario": brl(line.quote.price),
             "subtotal": brl(line.subtotal),
             **({"promocao": f"{line.quote.promotion.discount_percent}% off, de {brl(line.quote.list_price)}"}
                if line.quote.promotion else {})}
            for line in cart.lines
        ],
        "total": brl(cart.total),
        "total_no_pix": brl(cart.pix_total) + (" (5% de desconto só nos itens sem promoção)"
                                               if any(l.quote.promotion for l in cart.lines) else " (5% de desconto)"),
        "parcelamento_maximo": f"{n}x de {brl(installment_value(cart.total, n))} sem juros",
        "combinar_formas_de_pagamento": ("permitido (compra acima de " + brl(PAYMENT_COMBINATION_MIN) + ")")
        if cart.allows_payment_combination else f"não disponível (só acima de {brl(PAYMENT_COMBINATION_MIN)})",
    }
    if args.installments:
        content["parcelamento_solicitado"] = _installment_request(cart.total, args.installments)
    if args.city:
        content["entrega"] = shipping_quote(args.city, cart.total, [p for p, _ in resolved])
        fee = local_shipping_fee(args.city, cart.total)
        if fee is not None:
            content["total_com_frete"] = brl(cart.total + fee)
    if problems:
        content["problemas"] = problems
    return ToolOutcome(content)


class ShippingArgs(BaseModel):
    city: str = Field(..., description="cidade de entrega")
    order_value: float | None = Field(None, description="valor do pedido em reais, se conhecido")
    products: list[str] = Field(default_factory=list, description="produtos do pedido, se conhecidos")


def shipping(args: ShippingArgs, ctx: ToolContext) -> ToolOutcome:
    products = [r.product for r in (lookup(ctx.data, name) for name in args.products) if r.product]
    value = to_money(args.order_value) if args.order_value is not None else None
    return ToolOutcome(shipping_quote(args.city, value, products))


# --- policies -----------------------------------------------------------------------

class GetPolicyArgs(BaseModel):
    topic: str = Field(..., description="tema da política (um dos ids listados)")


def get_policy(args: GetPolicyArgs, ctx: ToolContext) -> ToolOutcome:
    doc = ctx.knowledge.policies.get(args.topic.strip().lower())
    if not doc:
        return ToolOutcome({"erro": f"tema '{args.topic}' não existe", "temas": list(ctx.knowledge.policies)})
    return ToolOutcome({"tema": doc.id, "titulo": doc.title, "texto": doc.body})


# --- customer and orders ------------------------------------------------------------

class VerifyCustomerArgs(BaseModel):
    order_id: int | None = Field(None, description="número do pedido")
    email: str | None = Field(None, description="e-mail do cadastro")
    phone: str | None = Field(None, description="telefone do cadastro")


_VERIFY_RESULT = {
    DecisionKind.ACTION: "verificado",
    DecisionKind.WAIT: "faltam_dados",
    DecisionKind.REJECT: "dados_nao_conferem",
    DecisionKind.ESCALATE: "bloqueado",
}


def verify_customer(args: VerifyCustomerArgs, ctx: ToolContext) -> ToolOutcome:
    claim = IdentityClaim(args.order_id, args.email, args.phone)
    result = verify_identity(ctx.data, claim, ctx.state)
    decision = result.decision
    content: dict = {"resultado": _VERIFY_RESULT[decision.kind], "mensagem": decision.reason}
    if decision.kind == DecisionKind.ACTION:
        customer = ctx.data.customers[decision.state_updates["customer_id"]]
        content["cliente"] = customer.name.split()[0]
    elif decision.kind == DecisionKind.REJECT:
        attempts = decision.state_updates.get("failed_attempts", 0)
        content["tentativas_restantes"] = MAX_FAILED_ATTEMPTS - attempts
        content["instrucao"] = "não diga qual dado não confere; peça para o cliente conferir e tentar de novo"
    elif decision.kind == DecisionKind.ESCALATE:
        content["instrucao"] = "ofereça atendimento humano com open_ticket"
    return ToolOutcome(content, state_updates=decision.state_updates, decision=result.explain())


class GetOrdersArgs(BaseModel):
    order_id: int | None = Field(None, description="número do pedido; vazio lista os pedidos do cliente verificado")


def get_orders(args: GetOrdersArgs, ctx: ToolContext) -> ToolOutcome:
    today = ctx.now.date()
    customer_id = ctx.state.get("customer_id")
    if args.order_id is not None:
        return ToolOutcome(order_view(ctx.data, ctx.data.orders[args.order_id], today))
    orders = sorted((o for o in ctx.data.orders.values() if o.customer_id == customer_id),
                    key=lambda o: o.order_date, reverse=True)
    return ToolOutcome({"pedidos": [order_view(ctx.data, o, today) for o in orders]})


class CheckReturnArgs(BaseModel):
    order_id: int = Field(..., description="número do pedido")
    reason: Literal["arrependimento", "defeito", "preferencia"] | None = Field(
        None, description="arrependimento (desistiu), defeito (problema de fabricação) ou preferencia "
                          "(cor/modelo); deixe vazio para avaliar todos os caminhos")


_RETURN_RESULT = {
    DecisionKind.FINAL: "elegivel",
    DecisionKind.REJECT: "nao_elegivel",
    DecisionKind.ESCALATE: "encaminhar_para_equipe",
    DecisionKind.WAIT: "aguardar",
}


def check_return_tool(args: CheckReturnArgs, ctx: ToolContext) -> ToolOutcome:
    order = ctx.data.orders[args.order_id]
    reasons = [args.reason] if args.reason else list(REASONS)
    results = [(reason, check_return(order, reason, ctx.now.date())) for reason in reasons]
    if len({result.decision.rule_id for _, result in results}) == 1:
        results = results[:1]  # e.g. a cancelled order: the same answer for every reason

    content = {
        "pedido": order.id,
        "avaliacoes": [
            {"motivo": reason if len(results) > 1 or args.reason else "qualquer",
             "resultado": _RETURN_RESULT[result.decision.kind],
             "explicacao": result.decision.reason,
             "detalhes": result.decision.value,
             "regra_aplicada": result.decision.rule_id}
            for reason, result in results
        ],
        "instrucao": "explique as regras; não aprove nem garanta nada além delas; para seguir, ofereça open_ticket",
    }
    decision = {
        "outcome": " / ".join(result.decision.kind.value for _, result in results),
        "rule_id": " / ".join(result.decision.rule_id for _, result in results),
        "checked": [step for _, result in results for step in result.explain()["checked"]],
    }
    return ToolOutcome(content, decision=decision)


class OpenTicketArgs(BaseModel):
    kind: Literal["reclamacao", "atendimento_humano", "cancelamento", "troca_devolucao", "outro"]
    summary: str = Field(..., description="resumo do caso em uma ou duas frases")
    contact: str | None = Field(None, description="telefone ou e-mail para retorno (obrigatório se não verificado)")


def open_ticket(args: OpenTicketArgs, ctx: ToolContext) -> ToolOutcome:
    customer_id = ctx.state.get("customer_id")
    if customer_id is None and not (args.contact and args.contact.strip()):
        return ToolOutcome({"erro": "peça um telefone ou e-mail de contato antes de abrir o chamado"})

    protocol = f"EM-{ctx.now:%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"
    tickets = [*(ctx.state.get("tickets") or []), protocol]
    ticket = {"protocolo": protocol, "criado_em": ctx.now.isoformat(), "tipo": args.kind,
              "resumo": args.summary, "cliente_id": customer_id, "contato": args.contact}
    ctx.tickets_path.parent.mkdir(parents=True, exist_ok=True)
    with ctx.tickets_path.open("a", encoding="utf-8") as handle:
        handle.write(to_json(ticket) + "\n")

    content = {"protocolo": protocol, "retorno": "a equipe retorna em até 24 horas úteis"}
    status = store_status(ctx.now)
    if not status["loja_aberta"]:
        content["equipe_volta"] = status["proxima_abertura"]
    return ToolOutcome(content, state_updates={"tickets": tickets})


# --- registry -----------------------------------------------------------------------

def build_tools(data: StoreData, knowledge: KnowledgeBase) -> dict[str, ToolSpec]:
    categories = ", ".join(c.name for c in data.categories.values())
    specs = [
        ToolSpec("search_products",
                 "Busca/filtra o catálogo em tempo real (preço, promoção, disponibilidade). Use para listas e "
                 f"filtros por categoria, palavra-chave ou faixa de preço. Categorias: {categories}.",
                 SearchProductsArgs, search_products),
        ToolSpec("get_product",
                 "Detalhes de UM produto: especificações, disponibilidade, preço, promoção ativa, valor no PIX, "
                 "parcelamento máximo (e se N parcelas são permitidas) e alternativas quando indisponível.",
                 GetProductArgs, get_product),
        ToolSpec("quote_order",
                 "Orçamento de um ou mais itens: total, total no PIX, parcelamento, combinação de pagamentos e "
                 "frete se a cidade for informada.",
                 QuoteOrderArgs, quote_order),
        ToolSpec("shipping_quote",
                 "Frete e prazo de entrega para uma cidade (Campo Grande: motoboy; outras: Correios/Jadlog).",
                 ShippingArgs, shipping),
        ToolSpec("get_policy",
                 "Carrega o texto de uma política da loja. Use para regras gerais (endereço, horário, pagamento, "
                 "trocas, frete, promoções, garantia, privacidade).",
                 GetPolicyArgs, get_policy,
                 schema_overrides={"topic": {"enum": list(knowledge.policies)}}),
        ToolSpec("verify_customer",
                 "Confirma a identidade do cliente (LGPD). Precisa de 2 dados: número do pedido + e-mail ou "
                 "telefone (ou e-mail + telefone). Obrigatório antes de get_orders e check_return.",
                 VerifyCustomerArgs, verify_customer),
        ToolSpec("get_orders",
                 "Status, itens, rastreio e previsão de entrega dos pedidos do cliente verificado.",
                 GetOrdersArgs, get_orders, requires_identity=True),
        ToolSpec("check_return",
                 "Aplica as regras de troca, devolução e garantia a um pedido do cliente verificado.",
                 CheckReturnArgs, check_return_tool, requires_identity=True),
        ToolSpec("open_ticket",
                 "Registra um chamado para a equipe humana (reclamação, atendimento humano, cancelamento, "
                 "troca/devolução). Retorno em até 24h úteis.",
                 OpenTicketArgs, open_ticket, effects=("write",)),
    ]
    return {spec.name: spec for spec in specs}

"""Prices, promotions, PIX discount and installment rules (manual sections 3 and 6)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..data.loader import Product, Promotion, StoreData
from ..decisions import Decision, PolicyResult, Rule, RulePolicy
from .money import brl, to_money

PIX_DISCOUNT = Decimal("0.05")
PAYMENT_COMBINATION_MIN = Decimal("2000")
MAX_INSTALLMENTS = 12

# Manual 3.1. The summary table says "minimum installment R$ 100" for credit
# cards, but 3.1 details tiers; we follow the more specific tiers (README).
INSTALLMENT_TIERS = (
    (1, 3, Decimal("50")),
    (4, 6, Decimal("80")),
    (7, 12, Decimal("100")),
)


def installment_value(amount: Decimal, installments: int) -> Decimal:
    return to_money(Decimal(amount) / installments)


def _tier_rule(low: int, high: int, minimum: Decimal) -> Rule:
    def then(observation: dict, _state: dict) -> Decision:
        n, value = observation["installments"], observation["installment_value"]
        if value >= minimum:
            return Decision.finish(True, reason=f"{n}x de {brl(value)} respeita a parcela mínima de "
                                                f"{brl(minimum)} para {low}x a {high}x")
        return Decision.reject(f"{n}x de {brl(value)} fica abaixo da parcela mínima de "
                               f"{brl(minimum)} para {low}x a {high}x", value=False)

    return Rule(
        f"INST_{low}_{high}",
        lambda o, s: low <= o["installments"] <= high,
        then,
        priority=10,
        description=f"{low}x a {high}x sem juros: parcela mínima {brl(minimum)}",
    )


INSTALLMENT_POLICY = RulePolicy("installments", [
    Rule("INST_RANGE", lambda o, s: not 1 <= o["installments"] <= MAX_INSTALLMENTS,
         Decision.reject(f"o parcelamento vai de 1x a {MAX_INSTALLMENTS}x", value=False), priority=100,
         description=f"cartão de crédito: de 1x a {MAX_INSTALLMENTS}x"),
    Rule("INST_SINGLE", lambda o, s: o["installments"] == 1,
         Decision.finish(True, reason="1x no cartão é sempre permitido"), priority=50,
         description="pagamento em 1x não tem parcela mínima"),
    *(_tier_rule(low, high, minimum) for low, high, minimum in INSTALLMENT_TIERS),
])


def check_installments(amount: Decimal, installments: int) -> PolicyResult:
    value = installment_value(amount, installments) if installments > 0 else Decimal(0)
    return INSTALLMENT_POLICY.decide({"amount": to_money(amount), "installments": installments,
                                      "installment_value": value})


def installment_options(amount: Decimal) -> list[tuple[int, Decimal]]:
    """Every allowed (installments, value) pair, in ascending order."""

    return [
        (n, installment_value(amount, n))
        for n in range(1, MAX_INSTALLMENTS + 1)
        if check_installments(amount, n).decision.allowed
    ]


def max_installments(amount: Decimal) -> int:
    return installment_options(amount)[-1][0]


def active_promotion(data: StoreData, product_id: int) -> Promotion | None:
    """Promotions are not cumulative: if several are active, the best one applies."""

    active = [p for p in data.promotions_for(product_id) if p.is_active]
    return max(active, key=lambda p: p.discount_percent, default=None)


@dataclass(frozen=True)
class PriceQuote:
    list_price: Decimal
    price: Decimal  # what the customer pays by card/boleto (promotional if any)
    promotion: Promotion | None
    pix_price: Decimal | None  # None when a promotion is active (not cumulative)

    @property
    def best_cash_price(self) -> Decimal:
        return self.pix_price if self.pix_price is not None else self.price

    def to_dict(self) -> dict:
        n = max_installments(self.price)
        data = {
            "preco_tabela": brl(self.list_price),
            "preco_final": brl(self.price),
            "pix": (brl(self.pix_price) + " (5% de desconto no PIX)") if self.pix_price is not None
            else "sem desconto extra no PIX: promoções não são cumulativas",
            "parcelamento_maximo": f"{n}x de {brl(installment_value(self.price, n))} sem juros",
        }
        if self.promotion:
            data["promocao"] = (f"{self.promotion.description}: {self.promotion.discount_percent}% off "
                                f"(de {brl(self.list_price)} por {brl(self.price)})")
        return data


def quote(data: StoreData, product: Product) -> PriceQuote:
    promo = active_promotion(data, product.id)
    if promo:
        price = to_money(product.price * (100 - promo.discount_percent) / 100)
        return PriceQuote(product.price, price, promo, None)
    return PriceQuote(product.price, product.price, None, to_money(product.price * (1 - PIX_DISCOUNT)))


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int
    quote: PriceQuote

    @property
    def subtotal(self) -> Decimal:
        return self.quote.price * self.quantity

    @property
    def pix_subtotal(self) -> Decimal:
        return self.quote.best_cash_price * self.quantity


@dataclass(frozen=True)
class CartQuote:
    lines: tuple[CartLine, ...]

    @property
    def total(self) -> Decimal:
        return to_money(sum((line.subtotal for line in self.lines), Decimal(0)))

    @property
    def pix_total(self) -> Decimal:
        """PIX 5% applies only to lines that are not already on promotion."""
        return to_money(sum((line.pix_subtotal for line in self.lines), Decimal(0)))

    @property
    def allows_payment_combination(self) -> bool:
        return self.total > PAYMENT_COMBINATION_MIN


def quote_cart(data: StoreData, items: list[tuple[Product, int]]) -> CartQuote:
    return CartQuote(tuple(CartLine(product, qty, quote(data, product)) for product, qty in items))

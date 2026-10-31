from decimal import Decimal

import pytest

from emporio.domain.money import brl, find_brl_amounts
from emporio.domain.pricing import check_installments, max_installments, quote, quote_cart


def test_brl_formatting():
    assert brl(Decimal("2089.05")) == "R$ 2.089,05"
    assert brl(Decimal("11499")) == "R$ 11.499,00"
    assert brl(Decimal("35")) == "R$ 35,00"


@pytest.mark.parametrize("text, expected", [
    ("custa R$ 2.199,00 à vista", Decimal("2199.00")),
    ("custa R$2199", Decimal("2199.00")),
    ("custa R$ 2.199", Decimal("2199.00")),
    ("parcela de R$ 87,84.", Decimal("87.84")),
    ("sai por R$ 1199.90", Decimal("1199.90")),
])
def test_brl_mentions_are_parsed_in_both_styles(text, expected):
    [(_, values)] = find_brl_amounts(text)
    assert expected in values


def test_regular_product_gets_pix_discount(data):
    takamine = data.products[95]  # Takamine GD20, R$ 2.199
    q = quote(data, takamine)
    assert q.promotion is None
    assert q.price == Decimal("2199.00")
    assert q.pix_price == Decimal("2089.05")


def test_promotional_price_is_not_combined_with_pix(data):
    ohana = data.products[121]  # Ohana CK-20, R$ 549 with an active 20% promotion
    q = quote(data, ohana)
    assert q.promotion and q.promotion.discount_percent == 20
    assert q.price == Decimal("439.20")
    assert q.pix_price is None
    assert "de R$ 549,00 por R$ 439,20" in q.to_dict()["promocao"]


def test_inactive_promotions_are_ignored(data):
    assert quote(data, data.products[96]).promotion is None  # two rows, both inactive


@pytest.mark.parametrize("amount, n, allowed", [
    ("439.20", 5, True),    # 87,84 >= 80
    ("439.20", 6, False),   # 73,20 < 80
    ("2199", 12, True),     # 183,25 >= 100
    ("159.90", 3, True),    # 53,30 >= 50
    ("120", 3, False),      # 40,00 < 50
    ("120", 1, True),       # 1x is always allowed
    ("5000", 13, False),
])
def test_installment_tiers(amount, n, allowed):
    assert check_installments(Decimal(amount), n).decision.allowed is allowed


def test_installment_decision_explains_the_rule():
    result = check_installments(Decimal("439.20"), 6)
    assert result.decision.rule_id == "INST_4_6"
    assert "R$ 73,20" in result.decision.reason and "R$ 80,00" in result.decision.reason


def test_max_installments(data):
    assert max_installments(Decimal("439.20")) == 5
    assert max_installments(Decimal("2199")) == 12


def test_cart_applies_pix_only_to_non_promotional_items(data):
    cart = quote_cart(data, [(data.products[95], 1), (data.products[121], 1)])
    assert cart.total == Decimal("2638.20")  # 2199 + 439,20
    assert cart.pix_total == Decimal("2528.25")  # 2089,05 + 439,20
    assert cart.allows_payment_combination

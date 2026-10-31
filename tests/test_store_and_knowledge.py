from datetime import date, datetime
from decimal import Decimal

from emporio.config import STORE_TZ
from emporio.data.quality import run_checks
from emporio.domain.store import easter, holidays, shipping_quote, store_status


def _at(*args):
    return datetime(*args, tzinfo=STORE_TZ)


def test_store_open_on_weekday_afternoon(now):
    status = store_status(now)
    assert status["loja_aberta"] is True
    assert status["horario_hoje"] == "09:00 às 18:00"


def test_store_closed_saturday_afternoon_reopens_monday():
    status = store_status(_at(2026, 3, 28, 15, 0))  # Saturday
    assert status["loja_aberta"] is False
    assert "segunda-feira" in status["proxima_abertura"] and "09:00" in status["proxima_abertura"]


def test_store_closed_on_holiday():
    assert easter(2026) == date(2026, 4, 5)
    assert holidays(2026)[date(2026, 4, 3)] == "Sexta-feira Santa"
    status = store_status(_at(2026, 4, 3, 10, 0))
    assert status["loja_aberta"] is False and "Sexta-feira Santa" in status["horario_hoje"]


def test_shipping_campo_grande_free_above_500():
    assert "grátis" in shipping_quote("Campo Grande", Decimal("599"))["frete"]
    assert shipping_quote("campo grande", Decimal("429.90"))["frete"].startswith("R$ 35,00")
    assert shipping_quote("Campo Grande", Decimal("500"))["frete"].startswith("R$ 35,00")  # "acima de"


def test_shipping_other_city_flags_large_items(data):
    quote = shipping_quote("Dourados", Decimal("13285"), [data.products[140]])
    assert len(quote["opcoes"]) == 3
    assert "Pearl" in quote["frete_especial"]


def test_policies_load_with_index(knowledge):
    assert {"horario", "pagamento", "trocas-devolucoes", "frete-entregas", "garantia"} <= set(knowledge.policies)
    assert "editorial" not in knowledge.policies["pagamento"].body.lower()
    assert "`horario`" in knowledge.policy_index()
    assert "Lia" in knowledge.persona and "C1" in knowledge.constitution


def test_quality_report_finds_known_issues(data, today):
    codes = {(f.code, f.message.split(":")[0]) for f in run_checks(data, today)}
    found = {code for code, _ in codes}
    assert {"CATEGORY_EMPTY", "DISCONTINUED_WITH_STOCK", "ORDER_TOTAL_MISMATCH", "ORDER_INSTALLMENT_RULE",
            "CUSTOMER_DUPLICATE_EMAIL", "ORDER_LATE", "ORDER_COMING_SOON_PRODUCT"} <= found

"""Opening hours, holidays and shipping rules (manual sections 2 and 5)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from ..data.loader import Product
from .catalog import normalize
from .money import brl

WEEKDAYS = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")

# weekday() -> (opens, closes); None = closed
WEEKLY_HOURS: dict[int, tuple[time, time] | None] = {
    0: (time(9), time(18)), 1: (time(9), time(18)), 2: (time(9), time(18)),
    3: (time(9), time(18)), 4: (time(9), time(18)), 5: (time(9), time(13)), 6: None,
}


def easter(year: int) -> date:
    """Anonymous Gregorian algorithm."""

    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def holidays(year: int) -> dict[date, str]:
    """National holidays plus Mato Grosso do Sul and Campo Grande ones (configurable list)."""

    fixed = {
        (1, 1): "Confraternização Universal", (4, 21): "Tiradentes", (5, 1): "Dia do Trabalho",
        (8, 26): "Aniversário de Campo Grande", (9, 7): "Independência do Brasil",
        (10, 11): "Criação do Estado de MS", (10, 12): "Nossa Senhora Aparecida", (11, 2): "Finados",
        (11, 15): "Proclamação da República", (11, 20): "Dia da Consciência Negra", (12, 25): "Natal",
    }
    result = {date(year, month, day): name for (month, day), name in fixed.items()}
    result[easter(year) - timedelta(days=2)] = "Sexta-feira Santa"
    return result


def hours_on(day: date) -> tuple[time, time] | None:
    if day in holidays(day.year):
        return None
    return WEEKLY_HOURS[day.weekday()]


def _describe_day(day: date, today: date) -> str:
    label = f"{WEEKDAYS[day.weekday()]}, {day:%d/%m}"
    if day == today:
        return f"hoje ({label})"
    if day == today + timedelta(days=1):
        return f"amanhã ({label})"
    return label


def store_status(now: datetime) -> dict:
    today = now.date()
    hours = hours_on(today)
    holiday = holidays(today.year).get(today)
    is_open = bool(hours and hours[0] <= now.time() < hours[1])
    status = {
        "agora": f"{WEEKDAYS[today.weekday()]}, {today:%d/%m/%Y} {now:%H:%M}",
        "loja_aberta": is_open,
        "horario_hoje": f"{hours[0]:%H:%M} às {hours[1]:%H:%M}" if hours
        else f"fechado ({holiday})" if holiday else "fechado",
    }
    if not is_open:
        day = today if hours and now.time() < hours[0] else today + timedelta(days=1)
        while hours_on(day) is None:
            day += timedelta(days=1)
        status["proxima_abertura"] = f"{_describe_day(day, today)} às {hours_on(day)[0]:%H:%M}"
    return status


# --- shipping -------------------------------------------------------------------

FREE_SHIPPING_ABOVE = Decimal("500")
LOCAL_FEE = Decimal("35")
# Only Campo Grande is confirmed by the data; extend with the metro-area cities if needed.
LOCAL_CITIES = {"campo grande"}
CARRIERS = [
    {"modalidade": "PAC (Correios)", "prazo": "5 a 12 dias úteis"},
    {"modalidade": "SEDEX (Correios)", "prazo": "2 a 5 dias úteis"},
    {"modalidade": "Jadlog (.package)", "prazo": "3 a 8 dias úteis"},
]


def is_large_item(product: Product) -> bool:
    """Acoustic drums, digital pianos and double basses may need a special freight quote."""

    name = normalize(product.name)
    return ((product.category_id == 3 and "acustica" in name)
            or (product.category_id == 4 and "piano" in name)
            or (product.category_id == 8 and "contrabaixo" in name))


def shipping_quote(city: str, order_value: Decimal | None = None, products: list[Product] | None = None) -> dict:
    large = [p.name for p in products or [] if is_large_item(p)]
    if normalize(city) in LOCAL_CITIES:
        quote = {"regiao": "Região Metropolitana de Campo Grande", "entrega": "motoboy próprio, 1 a 3 dias úteis",
                 "contato": "o cliente recebe uma ligação antes da entrega"}
        if order_value is None:
            quote["frete"] = f"grátis acima de {brl(FREE_SHIPPING_ABOVE)}; abaixo disso, taxa fixa de {brl(LOCAL_FEE)}"
        elif order_value > FREE_SHIPPING_ABOVE:
            quote["frete"] = f"grátis (pedido de {brl(order_value)}, acima de {brl(FREE_SHIPPING_ABOVE)})"
        else:
            quote["frete"] = (f"{brl(LOCAL_FEE)} (pedido de {brl(order_value)}; frete grátis só acima de "
                              f"{brl(FREE_SHIPPING_ABOVE)})")
        return quote

    quote = {
        "regiao": f"outra cidade ({city})",
        "opcoes": CARRIERS,
        "frete": "calculado no fechamento do pedido pelo CEP, peso e dimensões; não temos o valor aqui",
        "seguro": "todos os envios têm rastreamento e seguro contra extravio e avaria incluídos",
    }
    if large:
        quote["frete_especial"] = f"{', '.join(large)}: instrumento de grande porte, pode exigir cotação individual"
    return quote

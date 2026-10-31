"""Money helpers: Decimal arithmetic and Brazilian formatting/parsing."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def brl(value: Decimal | float | int | str) -> str:
    """Format as Brazilian currency: ``R$ 1.234,56``."""

    amount = to_money(value)
    sign = "-" if amount < 0 else ""
    integer, cents = f"{abs(amount):.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}R$ {'.'.join(groups)},{cents}"


# "R$ 1.234,56", "R$1234,56", "R$ 2.199", "R$ 1199.90", "R$ 500"
_BRL_MENTION = re.compile(r"R\$\s*(\d[\d.,]*\d|\d)")


def number_values(raw: str) -> set[Decimal]:
    """All plausible values of a number written in pt-BR or en-US style."""

    candidates: list[str] = []
    if "," in raw:  # pt-BR: dots group thousands, comma is the decimal separator
        candidates.append(raw.replace(".", "").replace(",", "."))
        candidates.append(raw.replace(",", ""))  # en-US "1,000.50"
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", raw):  # "2.199" -> 2199 (also 2.199 if a decimal)
        candidates.append(raw.replace(".", ""))
        if raw.count(".") == 1:
            candidates.append(raw)
    else:
        candidates.append(raw)

    values: set[Decimal] = set()
    for candidate in candidates:
        try:
            values.add(to_money(candidate))
        except ArithmeticError:
            pass
    return values


def find_brl_amounts(text: str) -> list[tuple[str, set[Decimal]]]:
    """Every ``R$`` amount in ``text`` as (original text, possible values)."""

    found = []
    for match in _BRL_MENTION.finditer(text):
        raw = match.group(1).rstrip(".,")
        values = number_values(raw)
        if values:
            found.append((match.group(0).rstrip(".,"), values))
    return found

from decimal import Decimal

import pytest

from emporio.domain.catalog import Availability, alternatives, availability, find_category, lookup, search


def test_case_example_acoustic_guitars_up_to_1000(data):
    """'Quais opções de violões disponíveis custando até R$1000?'"""
    result = search(data, category="violão", max_price=Decimal("1000"))
    ids = {p.id for p in result.products}
    assert result.category.name == "Violões"
    assert 96 not in ids   # Giannini GF-3D: active but stock 0
    assert 113 not in ids  # Shelby SN-7C: discontinued
    assert all(p.price <= 1000 for p in result.products)
    assert len(ids) == 12


@pytest.mark.parametrize("text, expected", [
    ("violao", "Violões"), ("Violões", "Violões"), ("ukulele", "Ukuleles"), ("guitarra", "Guitarras"),
    ("teclados", "Teclados e Pianos"),
])
def test_category_matching_is_fuzzy(data, text, expected):
    assert find_category(data, text).name == expected


def test_unknown_category_is_reported(data):
    result = search(data, category="aviões")
    assert result.products == [] and result.unknown_category == "aviões"


def test_seven_string_guitars_are_instruments_not_accessories(data):
    names = [p.name for p in search(data, query="violão 7 cordas").products]
    assert names and all("7 Cordas" in name for name in names)


def test_free_text_search_with_synonyms(data):
    names = [p.name for p in search(data, query="ukulele tenor").products]
    assert names and all("Tenor" in name for name in names)
    electric_nylon = search(data, category="violão", query="elétrico nylon").products
    assert electric_nylon and all("Elétrico" in p.name and p.specs["strings"] == "nylon" for p in electric_nylon)


@pytest.mark.parametrize("query, product_id", [
    ("Takamine GD20", 95), ("takamine gd 20", 95), ("Les Paul", 131), ("ohana ck20", 121), ("95", 95),
])
def test_lookup_resolves_names_and_ids(data, query, product_id):
    assert lookup(data, query).product.id == product_id


def test_ambiguous_lookup_returns_candidates(data):
    result = lookup(data, "Yamaha")
    assert result.product is None and len(result.candidates) > 1


@pytest.mark.parametrize("product_id, expected", [
    (95, Availability.AVAILABLE), (96, Availability.OUT_OF_STOCK),
    (113, Availability.DISCONTINUED), (136, Availability.DISCONTINUED),  # 136 has stock, status wins
    (130, Availability.COMING_SOON),
])
def test_availability(data, product_id, expected):
    assert availability(data.products[product_id]) == expected


def test_alternatives_are_available_and_same_category(data):
    alts = alternatives(data, data.products[96])
    assert len(alts) == 3
    assert all(p.category_id == 5 and availability(p) == Availability.AVAILABLE for p in alts)

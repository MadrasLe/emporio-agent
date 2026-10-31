from decimal import Decimal

import pytest

from emporio.domain.bm25 import BM25
from emporio.domain.catalog import (
    Availability,
    alternatives,
    availability,
    description_brand_conflict,
    find_category,
    lookup,
    search,
)


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
    electric_nylon = search(data, category="violão", query="elétrico nylon").products[:5]
    assert all("Elétrico" in p.name and p.specs["strings"] == "nylon" for p in electric_nylon)


def test_descriptive_queries_are_ranked_by_relevance(data):
    choro = search(data, query="violão bom pra tocar choro")
    assert choro.category.name == "Violões" and choro.category_inferred
    assert choro.products and all("choro" in p.description for p in choro.products)
    rock = search(data, query="guitarra para rock pesado")
    assert rock.category.name == "Guitarras" and rock.products[0].id == 131  # Les Paul: "ideal para rock"


def test_category_is_inferred_only_when_unambiguous(data):
    result = search(data, query="violão 7 cordas")  # 'cordas' also names "Cordas Orquestrais"
    assert result.category is None and not result.category_inferred


def test_words_that_match_nothing_fall_back_to_the_category(data):
    result = search(data, query="ukulele pra levar em viagem")
    assert result.text_matched is False
    assert result.products and all(p.category_id == 9 for p in result.products)


def test_item_from_an_empty_category_points_to_that_category(data):
    result = search(data, query="saxofone")
    assert result.products == [] and result.text_matched is False
    assert result.category.name == "Instrumentos de Sopro (Madeiras)"


def test_brand_conflicts_in_descriptions_are_detected(data):
    assert description_brand_conflict(data.products[135]) == {"fender"}  # "Music Man Bass 1X" vs Fender Jazz
    assert description_brand_conflict(data.products[95]) == set()


def test_bm25_prefers_rare_terms():
    index = BM25({1: ["violao", "choro"], 2: ["violao", "nylon"], 3: ["violao", "aco"]})
    assert index.idf["choro"] > index.idf["violao"]
    assert index.score(1, {"choro": 1.0}) > 0 and index.score(2, {"choro": 1.0}) == 0


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

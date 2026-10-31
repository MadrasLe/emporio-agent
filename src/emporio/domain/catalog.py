"""Catalog search, fuzzy product lookup, availability and alternatives."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from rapidfuzz import fuzz, process

from ..data.loader import Category, Product, StoreData
from .pricing import quote


class Availability(str, Enum):
    AVAILABLE = "disponivel"
    OUT_OF_STOCK = "sem_estoque"
    DISCONTINUED = "fora_de_linha"
    COMING_SOON = "em_breve"


AVAILABILITY_LABEL = {
    Availability.AVAILABLE: "disponível",
    Availability.OUT_OF_STOCK: "temporariamente sem estoque",
    Availability.DISCONTINUED: "fora de linha (não faz mais parte do catálogo)",
    Availability.COMING_SOON: "em breve (ainda não está à venda)",
}


def availability(product: Product) -> Availability:
    if product.status == "discontinued":
        return Availability.DISCONTINUED
    if product.status == "coming_soon":
        return Availability.COMING_SOON
    return Availability.AVAILABLE if product.stock > 0 else Availability.OUT_OF_STOCK


_STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "com", "para", "pra", "o", "a", "os", "as", "ate",
    "um", "uma", "em", "no", "na", "que", "tem", "voces", "quero", "algum", "alguma",
}


def normalize(text: str, *, glue_model_codes: bool = False) -> str:
    """Lowercase and strip accents. Optionally glue model codes: 'GD 20' -> 'gd20'."""

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    if glue_model_codes:
        text = re.sub(
            r"\b([a-z]{1,4}) (\d+)\b",
            lambda m: m.group(0) if m.group(1) in _STOPWORDS else m.group(1) + m.group(2),
            text,
        )
    return " ".join(text.split())


def _stem(word: str) -> str:
    """Crude Portuguese singular: 'violoes' -> 'violao', 'guitarras' -> 'guitarra'."""

    if word.endswith("oes"):
        return word[:-3] + "ao"
    if word.endswith("s") and len(word) > 3 and not word.isdigit():
        return word[:-1]
    return word


# Customer vocabulary -> words that appear in product names/specs (already stemmed).
_SYNONYMS = {
    "eletrico": ["eletrico", "eletrica", "eletroacustico", "electric"],
    "eletroacustico": ["eletrico", "eletroacustico"],
    "aco": ["aco", "steel"],
    "classico": ["nylon", "classico", "classical"],
    "baixo": ["baixo", "bas"],
    "teclado": ["teclado", "sintetizador", "synth"],
    "iniciante": ["iniciante", "estudante", "comecando"],
}


def _haystack(product: Product, category: Category | None) -> set[str]:
    words = [product.name, product.description, category.name if category else ""]
    words.extend(str(value) for value in product.specs.values())
    return {_stem(word) for word in normalize(" ".join(words)).split()}


def _token_matches(token: str, haystack: set[str]) -> bool:
    token = _stem(token)
    candidates = _SYNONYMS.get(token, [token])
    for candidate in candidates:
        if candidate in haystack:
            return True
        if len(candidate) >= 4 and any(
            word.startswith(candidate) or fuzz.ratio(candidate, word) >= 85 for word in haystack
        ):
            return True
    return False


def find_category(data: StoreData, text: str) -> Category | None:
    """'violao', 'violões', 'ukulele', 'guitarra' -> category (fuzzy, accent-insensitive)."""

    if not text:
        return None

    def stemmed(value: str) -> str:
        return " ".join(_stem(word) for word in normalize(value).split())

    choices = {cid: stemmed(c.name) for cid, c in data.categories.items()}
    best = process.extractOne(stemmed(text), choices, scorer=fuzz.WRatio)
    if best and best[1] >= 80:
        return data.categories[best[2]]
    return None


@dataclass(frozen=True)
class SearchResult:
    products: list[Product]
    category: Category | None
    unknown_category: str | None = None


def search(data: StoreData, *, query: str = "", category: str = "", min_price: Decimal | None = None,
           max_price: Decimal | None = None, include_unavailable: bool = False, limit: int = 15) -> SearchResult:
    """Filter the catalog. Price filters use the price the customer actually pays."""

    found_category = find_category(data, category) if category else None
    if category and found_category is None:
        return SearchResult([], None, unknown_category=category)

    tokens = [t for t in normalize(query).split() if t not in _STOPWORDS] if query else []
    results = []
    for product in data.products.values():
        if found_category and product.category_id != found_category.id:
            continue
        if not include_unavailable and availability(product) != Availability.AVAILABLE:
            continue
        price = quote(data, product).price
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        haystack = _haystack(product, data.categories.get(product.category_id))
        if tokens and not all(_token_matches(token, haystack) for token in tokens):
            continue
        results.append((price, product))

    results.sort(key=lambda item: (item[0], item[1].id))
    return SearchResult([product for _, product in results[:limit]], found_category)


@dataclass(frozen=True)
class LookupResult:
    product: Product | None
    candidates: list[Product]  # filled when the name is ambiguous or not found


def lookup(data: StoreData, name_or_id: str | int) -> LookupResult:
    """Resolve a product by id or (fuzzy) name. Ambiguous names return candidates."""

    text = str(name_or_id).strip()
    if text.isdigit() and int(text) in data.products:
        return LookupResult(data.products[int(text)], [])

    query = normalize(text, glue_model_codes=True)
    choices = {pid: normalize(p.name, glue_model_codes=True) for pid, p in data.products.items()}
    ranked = process.extract(query, choices, scorer=fuzz.WRatio, limit=5)
    ranked = [(score, data.products[pid]) for _, score, pid in ranked if score >= 60]
    if not ranked:
        return LookupResult(None, [])

    top_score, top = ranked[0]
    runner_up = ranked[1][0] if len(ranked) > 1 else 0
    if top_score >= 86 and top_score - runner_up >= 4:
        return LookupResult(top, [])
    return LookupResult(None, [product for _, product in ranked])


def alternatives(data: StoreData, product: Product, limit: int = 3) -> list[Product]:
    """Available products of the same category, closest in price first."""

    same_category = [
        p for p in data.products_in(product.category_id)
        if p.id != product.id and availability(p) == Availability.AVAILABLE
    ]
    return sorted(same_category, key=lambda p: abs(quote(data, p).price - product.price))[:limit]

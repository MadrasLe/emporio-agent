"""Catalog search, fuzzy product lookup, availability and alternatives.

Search is hybrid: hard filters (category, price, availability) decide what *can*
be shown; BM25 over name, description and specs decides the *order*, so a
descriptive request ("violão bom pra tocar choro") still finds the right items.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from rapidfuzz import fuzz, process

from ..data.loader import Category, Product, StoreData
from .bm25 import BM25
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


# --- text normalization ---------------------------------------------------------------

_STOPWORDS = {
    "de", "da", "do", "das", "dos", "e", "com", "para", "pra", "pro", "o", "a", "os", "as", "ate", "um", "uma",
    "uns", "umas", "em", "no", "na", "nos", "nas", "que", "tem", "ter", "voce", "voces", "quero", "queria",
    "gostaria", "procuro", "procurando", "preciso", "algum", "alguma", "me", "meu", "minha", "qual", "quais",
    "opcao", "opcoe", "opcoes", "modelo", "reais", "r", "mais", "muito", "bem", "por", "sobre", "ser", "eh",
}
_GENERIC_CATEGORY_WORDS = {"instrumento"}


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


def _terms(text: str) -> list[str]:
    return [_stem(word) for word in normalize(text).split() if word not in _STOPWORDS]


# Customer vocabulary -> words used in names/descriptions/specs (already stemmed).
_SYNONYMS = {
    "eletrico": ["eletrico", "eletrica", "eletroacustico", "electric"],
    "eletroacustico": ["eletrico", "eletroacustico"],
    "aco": ["aco", "steel"],
    "classico": ["nylon", "classico", "classical"],
    "baixo": ["baixo", "contrabaixo", "bas"],
    "teclado": ["teclado", "sintetizador", "synth", "piano"],
    "iniciante": ["iniciante", "estudante", "comecando"],
    "estudar": ["iniciante", "estudante"],
    "estudo": ["iniciante", "estudante"],
    "aprender": ["iniciante", "estudante"],
    "comecar": ["iniciante", "estudante"],
}

BRANDS = ("crafter", "fender", "giannini", "gibson", "ibanez", "kala", "kalani", "korg", "martin", "music man",
          "nord", "ohana", "pearl", "prs", "roland", "rozini", "shelby", "tagima", "takamine", "tama", "taylor",
          "yamaha")


def _brands_in(text: str) -> set[str]:
    padded = f" {normalize(text)} "
    return {brand for brand in BRANDS if f" {brand} " in padded}


def description_brand_conflict(product: Product) -> set[str]:
    """Brands cited in the description that are not the product's own (a data-entry error)."""

    in_name = _brands_in(product.name)
    return _brands_in(product.description) - in_name if in_name else set()


# --- BM25 index -------------------------------------------------------------------------

def _document_terms(product: Product, category: Category | None) -> list[str]:
    spec_values = [str(v) for v in product.specs.values() if str(v).lower() not in ("yes", "no")]
    terms = _terms(product.name) * 2  # the name matters more than the description
    terms += _terms(" ".join([category.name if category else "", product.description, *spec_values]))
    if str(product.specs.get("electronics", "")).lower() == "yes":
        terms.append("eletrico")
    return terms


_INDEXES: dict[int, tuple[StoreData, BM25]] = {}


def _index(data: StoreData) -> BM25:
    cached = _INDEXES.get(id(data))
    if cached is None or cached[0] is not data:
        docs = {p.id: _document_terms(p, data.categories.get(p.category_id)) for p in data.products.values()}
        cached = (data, BM25(docs))
        _INDEXES[id(data)] = cached
    return cached[1]


def _query_weights(tokens: list[str], vocabulary: set[str]) -> dict[str, float]:
    """Exact (and synonym) matches weigh 1.0; fuzzy/prefix matches for typos weigh 0.8."""

    weights: dict[str, float] = {}
    for token in tokens:
        for candidate in _SYNONYMS.get(token, [token]):
            if candidate in vocabulary:
                weights[candidate] = 1.0
            elif len(candidate) >= 4:
                for word in vocabulary:
                    if word.startswith(candidate) or fuzz.ratio(candidate, word) >= 85:
                        weights[word] = max(weights.get(word, 0.0), 0.8)
    return weights


# --- categories -------------------------------------------------------------------------

def _category_words(category: Category) -> set[str]:
    return set(_terms(category.name)) - _GENERIC_CATEGORY_WORDS


def find_category(data: StoreData, text: str) -> Category | None:
    """'violao', 'violões', 'ukulele', 'guitarra' -> category (fuzzy, accent-insensitive)."""

    if not text:
        return None
    choices = {cid: " ".join(_terms(c.name)) for cid, c in data.categories.items()}
    best = process.extractOne(" ".join(_terms(text)), choices, scorer=fuzz.WRatio)
    if best and best[1] >= 80:
        return data.categories[best[2]]
    return None


def infer_category(data: StoreData, tokens: list[str], *, use_descriptions: bool = False,
                   ) -> tuple[Category | None, set[str]]:
    """A category named in the free text ('guitarra para rock') when exactly one is named.

    With ``use_descriptions`` it also looks at what each category covers ('saxofone' -> wind instruments).
    """

    matches: dict[int, set[str]] = {}
    for category in data.categories.values():
        words = _category_words(category)
        if use_descriptions:
            words |= set(_terms(category.description))
        used = set(tokens) & words
        if used:
            matches[category.id] = used
    if len(matches) == 1:
        category_id, used = next(iter(matches.items()))
        return data.categories[category_id], used
    return None, set()


# --- search -----------------------------------------------------------------------------

RELATIVE_CUTOFF = 0.5  # keep results scoring at least half of the best one


@dataclass(frozen=True)
class SearchResult:
    products: list[Product]
    category: Category | None
    unknown_category: str | None = None
    category_inferred: bool = False
    text_matched: bool | None = None  # None: no free-text query; False: nothing matched the words


def search(data: StoreData, *, query: str = "", category: str = "", min_price: Decimal | None = None,
           max_price: Decimal | None = None, include_unavailable: bool = False, limit: int = 15) -> SearchResult:
    """Filter the catalog, then rank by BM25. Price filters use the price the customer actually pays."""

    chosen = find_category(data, category) if category else None
    if category and chosen is None:
        return SearchResult([], None, unknown_category=category)

    tokens = _terms(query) if query else []
    inferred = False
    if tokens and chosen is None:
        chosen, used = infer_category(data, tokens)
        inferred = chosen is not None
        tokens = [t for t in tokens if t not in used]
    elif chosen is not None:
        tokens = [t for t in tokens if t not in _category_words(chosen)]

    candidates = []
    for product in data.products.values():
        if chosen and product.category_id != chosen.id:
            continue
        if not include_unavailable and availability(product) != Availability.AVAILABLE:
            continue
        price = quote(data, product).price
        if (min_price is not None and price < min_price) or (max_price is not None and price > max_price):
            continue
        candidates.append((price, product))

    if not tokens:
        candidates.sort(key=lambda item: (item[0], item[1].id))
        return SearchResult([p for _, p in candidates[:limit]], chosen, category_inferred=inferred)

    index = _index(data)
    weights = _query_weights(tokens, index.vocabulary)
    scored = [(index.score(p.id, weights), price, p) for price, p in candidates]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        if chosen is None:
            # Maybe the customer named something a category covers but the catalog lacks ('saxofone').
            covering, _ = infer_category(data, tokens, use_descriptions=True)
            return SearchResult([], covering, category_inferred=covering is not None, text_matched=False)
        candidates.sort(key=lambda item: (item[0], item[1].id))  # fall back to the whole category
        return SearchResult([p for _, p in candidates[:limit]], chosen, category_inferred=inferred,
                            text_matched=False)

    best = max(score for score, _, _ in scored)
    ranked = sorted((item for item in scored if item[0] >= RELATIVE_CUTOFF * best),
                    key=lambda item: (-item[0], item[1], item[2].id))
    return SearchResult([p for _, _, p in ranked[:limit]], chosen, category_inferred=inferred, text_matched=True)


# --- lookup and alternatives ---------------------------------------------------------------

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

"""Embedding similarity over the catalog, used as a second ranking signal next to BM25.

The embedding provider is injected (``Embedder``), so this module stays free of
LLM/network code. Product vectors are computed once per model and cached on disk.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Protocol

from ..data.loader import Product, StoreData


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def product_text(product: Product, data: StoreData) -> str:
    category = data.categories.get(product.category_id)
    specs = ", ".join(f"{k}: {v}" for k, v in product.specs.items())
    return f"{product.name}. {category.name if category else ''}. {product.description} Especificações: {specs}"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class SemanticIndex:
    def __init__(self, embedder: Embedder, data: StoreData, cache_dir: Path | None = None):
        self.embedder = embedder
        self.data = data
        self.cache_dir = cache_dir
        self._vectors: dict[int, list[float]] | None = None

    @property
    def model(self) -> str:
        return self.embedder.model

    def _cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"embeddings-{re.sub(r'[^a-z0-9]+', '-', self.model.lower())}.json"

    def vectors(self) -> dict[int, list[float]]:
        if self._vectors is not None:
            return self._vectors
        texts = {p.id: product_text(p, self.data) for p in self.data.products.values()}
        fingerprint = hashlib.sha256(json.dumps(texts, sort_keys=True).encode("utf-8")).hexdigest()

        path = self._cache_path()
        if path and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                self._vectors = {int(k): v for k, v in cached["vectors"].items()}
                return self._vectors

        ids = list(texts)
        embedded = self.embedder.embed([texts[i] for i in ids])  # one batched call for the whole catalog
        self._vectors = dict(zip(ids, embedded))
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model, "fingerprint": fingerprint,
                                        "vectors": self._vectors}), encoding="utf-8")
        return self._vectors

    def rank(self, query: str, candidate_ids: list[int]) -> list[tuple[int, float]]:
        """Candidates ordered by cosine similarity to the query (most similar first)."""

        vectors = self.vectors()
        [query_vector] = self.embedder.embed([query])
        scored = [(pid, cosine(query_vector, vectors[pid])) for pid in candidate_ids if pid in vectors]
        return sorted(scored, key=lambda item: -item[1])


def reciprocal_rank_fusion(*rankings: list[int], k: int = 60) -> dict[int, float]:
    """Combine rankings by position only (robust to incomparable score scales)."""

    fused: dict[int, float] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + position)
    return fused

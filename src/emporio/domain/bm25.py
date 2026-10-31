"""Okapi BM25 over a small in-memory corpus (64 products: no search engine needed)."""

from __future__ import annotations

import math
from collections import Counter


class BM25:
    def __init__(self, documents: dict[int, list[str]], *, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.term_freqs = {doc_id: Counter(tokens) for doc_id, tokens in documents.items()}
        self.lengths = {doc_id: len(tokens) for doc_id, tokens in documents.items()}
        self.avg_length = sum(self.lengths.values()) / max(len(documents), 1)
        doc_freq = Counter(term for freqs in self.term_freqs.values() for term in freqs)
        n = len(documents)
        # BM25+ style idf: always positive, so very common terms still count a little.
        self.idf = {term: math.log((n - df + 0.5) / (df + 0.5) + 1) for term, df in doc_freq.items()}

    @property
    def vocabulary(self) -> set[str]:
        return set(self.idf)

    def score(self, doc_id: int, weighted_terms: dict[str, float]) -> float:
        freqs = self.term_freqs[doc_id]
        norm = self.k1 * (1 - self.b + self.b * self.lengths[doc_id] / self.avg_length)
        total = 0.0
        for term, weight in weighted_terms.items():
            tf = freqs.get(term, 0)
            if tf:
                total += weight * self.idf[term] * tf * (self.k1 + 1) / (tf + norm)
        return total

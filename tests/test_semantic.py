"""Hybrid search with a deterministic fake embedder (no network)."""

import unicodedata

import pytest

from emporio.domain.catalog import RANKING_BM25_FALLBACK, RANKING_HYBRID, search
from emporio.domain.semantic import SemanticIndex, reciprocal_rank_fusion

# Each dimension is a "concept"; texts mentioning it point that way.
CONCEPTS = [("viag", "viaj"), ("palco", "amplific", "captac"), ("quente", "encorpad"), ("iniciant", "estudant")]


class FakeEmbedder:
    model = "fake-embed"

    def __init__(self):
        self.calls: list[int] = []

    def embed(self, texts):
        self.calls.append(len(texts))
        vectors = []
        for text in texts:
            plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
            vectors.append([1.0 if any(word in plain for word in concept) else 0.0 for concept in CONCEPTS] + [0.1])
        return vectors


class BrokenEmbedder:
    model = "broken"

    def embed(self, texts):
        raise ConnectionError("429 Too Many Requests")


@pytest.fixture
def semantic(data):
    return SemanticIndex(FakeEmbedder(), data)


def test_paraphrase_found_by_embeddings(data, semantic):
    """BM25 alone has no match for 'viagem'; the Kala KA-15S is 'perfeito para... viajantes'."""
    assert search(data, query="ukulele pra levar em viagem").text_matched is False
    result = search(data, query="ukulele pra levar em viagem", semantic=semantic)
    assert result.ranking == RANKING_HYBRID
    assert result.products[0].id == 116
    assert all(p.category_id == 9 for p in result.products)


def test_hybrid_keeps_every_bm25_hit(data, semantic):
    bm25 = {p.id for p in search(data, query="violão bom pra tocar choro").products}
    hybrid = {p.id for p in search(data, query="violão bom pra tocar choro", semantic=semantic).products}
    assert bm25 <= hybrid


def test_embeddings_never_rank_the_whole_catalog_alone(data, semantic):
    result = search(data, query="saxofone", semantic=semantic)
    assert result.products == [] and result.category.name.startswith("Instrumentos de Sopro")


def test_provider_failure_falls_back_to_bm25(data):
    broken = SemanticIndex(BrokenEmbedder(), data)
    result = search(data, query="violão bom pra tocar choro", semantic=broken)
    assert result.ranking == RANKING_BM25_FALLBACK
    assert [p.id for p in result.products] == [p.id for p in search(data, query="violão bom pra tocar choro").products]


def test_product_vectors_are_cached_on_disk(data, tmp_path):
    first = FakeEmbedder()
    SemanticIndex(first, data, cache_dir=tmp_path).rank("violão", [95])
    assert first.calls == [len(data.products), 1]  # catalog once, then the query
    second = FakeEmbedder()
    SemanticIndex(second, data, cache_dir=tmp_path).rank("violão", [95])
    assert second.calls == [1]  # only the query


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([1, 2, 3], [3, 1, 4])
    assert max(fused, key=fused.get) == 1  # 1st and 2nd beats 3rd and 1st
    assert fused[4] < fused[2]

"""Embedding client for any OpenAI-compatible endpoint (OpenRouter by default)."""

from __future__ import annotations

from openai import OpenAI


class OpenAIEmbedder:
    def __init__(self, model: str, base_url: str, api_key: str, timeout: float = 30):
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=2)

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

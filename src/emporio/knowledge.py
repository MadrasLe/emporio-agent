"""Markdown knowledge base: store policies (loaded on demand), persona and constitution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    when_to_use: str
    body: str


def read_document(path: Path) -> Document:
    """Split YAML frontmatter from the markdown body. Editorial notes stay out of the body."""

    text = path.read_text(encoding="utf-8")
    meta: dict = {}
    body = text
    if text.startswith("---"):
        _, frontmatter, body = text.split("---", 2)
        meta = yaml.safe_load(frontmatter) or {}
    return Document(
        id=str(meta.get("id", path.stem)),
        title=str(meta.get("title", path.stem)),
        when_to_use=str(meta.get("when_to_use", "")),
        body=body.strip(),
    )


@dataclass(frozen=True)
class KnowledgeBase:
    persona: str
    constitution: str
    policies: dict[str, Document]

    def policy_index(self) -> str:
        """One line per policy: what the model sees before choosing one to load."""

        return "\n".join(f"- `{doc.id}`: {doc.title} — {doc.when_to_use}" for doc in self.policies.values())


def load_knowledge(knowledge_dir: Path) -> KnowledgeBase:
    policies = {
        doc.id: doc
        for doc in (read_document(path) for path in sorted((knowledge_dir / "policies").glob("*.md")))
    }
    return KnowledgeBase(
        persona=read_document(knowledge_dir / "persona.md").body,
        constitution=read_document(knowledge_dir / "constitution.md").body,
        policies=policies,
    )

"""Everything the agent needs at run time: settings, data, knowledge, model and tools."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from ..config import Settings, load_settings
from ..data.loader import StoreData, load_store_data
from ..knowledge import KnowledgeBase, load_knowledge
from .tools import ToolSpec, build_tools


class MissingAPIKey(RuntimeError):
    pass


def build_llm(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if not settings.llm_api_key:
        raise MissingAPIKey("LLM_API_KEY is not set. Copy .env.example to .env and add your OpenRouter key.")
    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=90,
        max_retries=3,
        default_headers={"X-Title": "Emporio da Musica Agent"},
    )


@dataclass
class Runtime:
    settings: Settings
    data: StoreData
    knowledge: KnowledgeBase
    llm: BaseChatModel
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def now(self) -> datetime:
        return self.settings.now()

    @property
    def tickets_path(self) -> Path:
        return self.settings.state_dir / "tickets.jsonl"


def load_runtime(settings: Settings | None = None, llm: BaseChatModel | None = None) -> Runtime:
    settings = settings or load_settings()
    data = load_store_data(settings.data_dir)
    knowledge = load_knowledge(settings.knowledge_dir)
    return Runtime(settings, data, knowledge, llm or build_llm(settings), build_tools(data, knowledge))


def open_checkpointer(settings: Settings):
    """Conversation history persisted in SQLite, keyed by thread (session) id."""

    from langgraph.checkpoint.sqlite import SqliteSaver

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.state_dir / "conversations.sqlite", check_same_thread=False)
    return SqliteSaver(connection)

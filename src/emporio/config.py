"""Runtime settings, read from environment variables (and an optional .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORE_TZ = ZoneInfo("America/Campo_Grande")

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "google/gemma-4-31b-it:free"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    knowledge_dir: Path
    state_dir: Path
    llm_base_url: str
    llm_api_key: str | None
    llm_model: str
    llm_temperature: float
    now_override: datetime | None = None

    def now(self) -> datetime:
        """Current time in the store's timezone (pinned when EMPORIO_NOW is set)."""
        return self.now_override or datetime.now(STORE_TZ)


def parse_now(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=STORE_TZ)


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or PROJECT_ROOT / ".env")
    return Settings(
        data_dir=Path(os.getenv("EMPORIO_DATA_DIR", PROJECT_ROOT / "data")),
        knowledge_dir=Path(os.getenv("EMPORIO_KNOWLEDGE_DIR", PROJECT_ROOT / "knowledge")),
        state_dir=Path(os.getenv("EMPORIO_STATE_DIR", PROJECT_ROOT / ".state")),
        llm_base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY"),
        llm_model=os.getenv("LLM_MODEL", DEFAULT_MODEL),
        llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
        now_override=parse_now(os.getenv("EMPORIO_NOW")),
    )

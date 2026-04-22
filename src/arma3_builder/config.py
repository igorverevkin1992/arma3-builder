"""Runtime configuration loaded from environment / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["anthropic", "openai", "ollama", "stub"]
RagBackend = Literal["memory", "qdrant"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARMA3_",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: ProviderName = Field(default="stub")

    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434")

    model_orchestrator: str = Field(default="claude-opus-4-7")
    model_narrative: str = Field(default="claude-sonnet-4-6")
    model_scripter: str = Field(default="claude-sonnet-4-6")
    model_config_master: str = Field(default="claude-sonnet-4-6")
    model_qa: str = Field(default="llama3:8b")

    rag_backend: RagBackend = Field(default="memory")
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str = Field(default="")

    output_dir: Path = Field(default=Path("./output"))
    qa_strict: bool = Field(default=True)
    max_repair_iterations: int = Field(default=5)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    override = os.environ.get("ARMA3_DATA_DIR")
    if override:
        return Path(override)
    return project_root() / "data"

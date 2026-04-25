"""Runtime configuration loaded from environment / .env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["gemini", "anthropic", "openai", "ollama", "stub"]
RagBackend = Literal["memory", "qdrant"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARMA3_",
        case_sensitive=False,
        extra="ignore",
    )

    llm_provider: ProviderName = Field(default="stub")

    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    ollama_base_url: str = Field(default="http://localhost:11434")
    # Gemini base URL — override only for proxies / Vertex AI.
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com")

    # Defaults are Gemini models. To use Anthropic/OpenAI/Ollama instead,
    # set ARMA3_LLM_PROVIDER and override the per-role model envs.
    model_orchestrator: str = Field(default="gemini-2.5-pro")
    model_narrative: str = Field(default="gemini-2.5-pro")
    model_scripter: str = Field(default="gemini-2.5-flash")
    model_config_master: str = Field(default="gemini-2.5-flash")
    model_qa: str = Field(default="gemini-2.5-flash-lite")

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

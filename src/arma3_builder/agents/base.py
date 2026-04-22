"""Base agent abstractions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..arma.classnames import ClassnameRegistry
from ..llm import LLMClient, get_llm_client
from ..rag import HybridRetriever
from ..utils.logger import get_logger


@dataclass
class AgentContext:
    """Shared bag passed through every agent on a single generation request.

    The Orchestrator owns it; subordinate agents read what they need and
    write artefacts/state back so subsequent agents have the context.
    """
    llm: LLMClient
    retriever: HybridRetriever
    registry: ClassnameRegistry
    memory: dict[str, Any] = field(default_factory=dict)


class Agent:
    role: str = "agent"
    model: str = ""

    def __init__(self, *, model: str | None = None) -> None:
        if model:
            self.model = model
        self.log = get_logger(self.__class__.__name__)

    def llm(self, ctx: AgentContext) -> LLMClient:
        return ctx.llm or get_llm_client()

"""A2A / ACP-style envelope used by the Orchestrator for inter-agent messages."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageKind(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    REPAIR = "repair"
    ERROR = "error"


class AgentMessage(BaseModel):
    """Generic envelope for A2A communication."""

    model_config = ConfigDict(extra="forbid")

    sender: str
    recipient: str
    kind: MessageKind
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = ""
    sent_at: datetime = Field(default_factory=datetime.utcnow)


class RepairRequest(BaseModel):
    """Structured repair instruction sent from QA back to a code-producing agent."""

    model_config = ConfigDict(extra="forbid")

    target_file: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    instructions: str = ""
    iteration: int = 1

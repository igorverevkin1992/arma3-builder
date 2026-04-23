"""Procedural Representation Protocol (PRP).

A typed, JSON-serialisable wire format used by agents to exchange campaign
descriptions without going through natural-language round-trips. Modelled with
Pydantic v2 so every message is validated at the boundary.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Brief (user input)
# --------------------------------------------------------------------------- #


class MissionBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    map: str = Field(description="World class name, e.g. 'Tanoa', 'Altis', 'VR'")
    side: Literal["WEST", "EAST", "INDEPENDENT", "CIVILIAN"] = "WEST"
    enemy_side: Literal["WEST", "EAST", "INDEPENDENT", "CIVILIAN"] = "EAST"
    objectives: list[str] = Field(default_factory=list)
    time_of_day: str = "12:00"
    weather: str = "clear"
    player_count: int = Field(default=1, ge=1, le=64)
    tags: list[str] = Field(default_factory=list)


class CampaignBrief(BaseModel):
    """The high-level brief produced by the Orchestrator from user prompt."""

    model_config = ConfigDict(extra="forbid")

    name: str
    author: str = "arma3-builder"
    overview: str
    mods: list[str] = Field(default_factory=list, description="e.g. ['rhsusf', 'cba_main']")
    factions: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of side -> faction classname (e.g. WEST -> 'rhs_faction_usmc_d')",
    )
    missions: list[MissionBrief] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Campaign name must not be empty")
        return v


# --------------------------------------------------------------------------- #
# FSM graph
# --------------------------------------------------------------------------- #


class StateKind(str, Enum):
    """Phase-A taxonomy used by the pacing analyser.

    The classifier maps FSM states onto one of these kinds so the timeline
    UI can colour and size them correctly. Unknown kinds default to GENERIC.
    """
    SETUP = "setup"
    TRAVEL = "travel"
    ENGAGEMENT = "engagement"
    STEALTH = "stealth"
    DIALOGUE = "dialogue"
    CUTSCENE = "cutscene"
    EXTRACTION = "extraction"
    GENERIC = "generic"
    TERMINAL = "terminal"


class TransitionKind(str, Enum):
    TRIGGER = "trigger"          # condition expression (SQF)
    TIMER = "timer"              # numeric timeout in seconds
    EVENT = "event"              # CBA event name
    OBJECTIVE = "objective"      # task completed/failed
    MANUAL = "manual"            # designer-pushed event


class FsmTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str
    kind: TransitionKind = TransitionKind.TRIGGER
    condition: str = "true"
    description: str = ""


class FsmState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    on_enter: list[str] = Field(default_factory=list, description="SQF statements")
    on_exit: list[str] = Field(default_factory=list)
    transitions: list[FsmTransition] = Field(default_factory=list)
    is_terminal: bool = False
    end_type: str | None = Field(
        default=None,
        description="If terminal: end1, end2, end3, loser, etc.",
    )
    kind: StateKind = Field(
        default=StateKind.GENERIC,
        description=(
            "Declared state category for the pacing analyser. If not set, "
            "the analyser will infer it from the label / on_enter actions."
        ),
    )
    expected_seconds: int | None = Field(
        default=None,
        description=(
            "Expected dwell time for this state under normal play. The "
            "pacing analyser uses it to build the mission timeline. "
            "None triggers a heuristic default per StateKind."
        ),
    )

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError("FSM state id must be alphanumeric/underscore")
        return v


class FsmGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initial: str
    states: list[FsmState]
    on_enter_global: list[str] = Field(
        default_factory=list,
        description=(
            "SQF statements that run once when the FSM is initialised, "
            "BEFORE any state on_enter fires. Use this to wire up "
            "namespace variables that transition conditions reference "
            "(e.g. `A3B_enemyLead = e1`)."
        ),
    )

    def state(self, sid: str) -> FsmState:
        for s in self.states:
            if s.id == sid:
                return s
        raise KeyError(sid)

    def end_types(self) -> set[str]:
        return {s.end_type for s in self.states if s.is_terminal and s.end_type}


# --------------------------------------------------------------------------- #
# Mission blueprint (units / waypoints / briefing / diary)
# --------------------------------------------------------------------------- #


class UnitPlacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classname: str
    side: str = "WEST"
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: float = 0.0
    name: str | None = None
    is_player: bool = False
    is_leader: bool = False
    group_id: str = "main"


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    position: tuple[float, float, float]
    type: str = "MOVE"
    behaviour: str = "AWARE"
    speed: str = "NORMAL"


class BriefingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tab: Literal["Situation", "Mission", "Execution", "Logistics", "Notes"] = "Situation"
    title: str
    text: str


class Diary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[BriefingEntry] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)


class Dialogue(BaseModel):
    """One radio line played during a mission."""

    model_config = ConfigDict(extra="forbid")

    id: str
    speaker: str = "HQ"
    text: str
    trigger_state: str | None = Field(
        default=None,
        description="If set, line is played when FSM enters this state",
    )


class Loadout(BaseModel):
    """Gear assignment for a single player role."""

    model_config = ConfigDict(extra="forbid")

    role_id: str                              # e.g. "team_leader", "medic"
    display_name: str                         # lobby-visible label
    uniform: str = ""
    vest: str = ""
    headgear: str = ""
    goggles: str = ""
    backpack: str = ""
    primary_weapon: str = ""
    primary_magazines: list[tuple[str, int]] = Field(default_factory=list)
    secondary_weapon: str = ""
    secondary_magazines: list[tuple[str, int]] = Field(default_factory=list)
    handgun: str = ""
    handgun_magazines: list[tuple[str, int]] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    linked_items: list[str] = Field(
        default_factory=list,
        description="NVG, maps, compass, etc. — items that sit in linked slots",
    )


class SupportAsset(BaseModel):
    """On-call support asset (CAS, artillery, medevac)."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cas", "artillery", "medevac", "transport", "ammo_drop"]
    name: str
    cooldown_seconds: int = 180
    uses: int = Field(default=3, ge=1, description="Max calls; 0 = unlimited")
    # Only used by specific kinds — kept as free-form strings so RAG-picked
    # classnames from different mod sets plug in without bespoke schemas.
    vehicle_classname: str = ""
    ammo_classname: str = ""
    ordnance_classname: str = ""


class MissionBlueprint(BaseModel):
    """Concrete mission representation produced by the Narrative Director."""

    model_config = ConfigDict(extra="forbid")

    mission_id: str = Field(
        description="Stable slug identifying the mission across agents (e.g. 'm01_silent_antenna')",
        default="",
    )
    brief: MissionBrief
    fsm: FsmGraph
    units: list[UnitPlacement] = Field(default_factory=list)
    waypoints: list[Waypoint] = Field(default_factory=list)
    diary: Diary = Field(default_factory=Diary)
    dialogue: list[Dialogue] = Field(default_factory=list)
    loadouts: list[Loadout] = Field(default_factory=list)
    support_assets: list[SupportAsset] = Field(default_factory=list)
    addons: list[str] = Field(default_factory=list)


class CampaignPlan(BaseModel):
    """Full plan emitted by the Narrative Director, consumed by code agents."""

    model_config = ConfigDict(extra="forbid")

    brief: CampaignBrief
    blueprints: list[MissionBlueprint]


# --------------------------------------------------------------------------- #
# Generated artefacts
# --------------------------------------------------------------------------- #


class GeneratedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str
    content: str
    kind: Literal["sqf", "sqm", "ext", "cpp", "txt", "json", "bikb", "fsm"] = "sqf"

    @field_validator("relative_path")
    @classmethod
    def _normalise(cls, v: str) -> str:
        v = v.strip().lstrip("/").replace("\\", "/")
        if not v:
            raise ValueError("relative_path must not be empty")
        return v


# --------------------------------------------------------------------------- #
# QA report
# --------------------------------------------------------------------------- #


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class QAFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line: int = 0
    column: int = 0
    severity: Severity = Severity.WARNING
    code: str
    message: str
    suggestion: str | None = None


class QAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[QAFinding] = Field(default_factory=list)
    iteration: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def errors(self) -> list[QAFinding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[QAFinding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]

    def is_clean(self, *, strict: bool) -> bool:
        if self.errors:
            return False
        if strict and self.warnings:
            return False
        return True


# --------------------------------------------------------------------------- #
# Pipeline result
# --------------------------------------------------------------------------- #


class GenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: CampaignPlan
    artifacts: list[GeneratedArtifact]
    qa: QAReport
    output_path: str | None = None
    iterations: int = 1
    # Phase-A extensions. Kept optional for backwards-compat with callers
    # who construct GenerationResult in tests.
    pacing: dict[str, Any] | None = None
    playtest: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None

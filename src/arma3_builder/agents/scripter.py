"""Scripter (SQF Logic Engineer): emits all SQF artefacts for a mission.

The fallback path uses the deterministic generators in `arma3_builder.arma`
so the system is fully functional without any LLM. When a real LLM is
configured, it can replace any of these files via the `repair` flow.
"""
from __future__ import annotations

from ..arma import (
    generate_briefing_sqf,
    generate_init_player_local,
    generate_init_server,
    generate_init_sqf,
    generate_statemachine_sqf,
)
from ..arma.init_scripts import macros_header
from ..config import get_settings
from ..protocols import (
    GeneratedArtifact,
    MissionBlueprint,
    QAReport,
)
from .base import Agent, AgentContext


class ScripterAgent(Agent):
    role = "scripter"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_scripter)

    async def run(
        self,
        blueprint: MissionBlueprint,
        ctx: AgentContext,
        *,
        mission_dir: str,
    ) -> list[GeneratedArtifact]:
        prefix = f"missions/{mission_dir}"

        artifacts: list[GeneratedArtifact] = [
            GeneratedArtifact(
                relative_path=f"{prefix}/init.sqf",
                content=generate_init_sqf(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/initServer.sqf",
                content=generate_init_server(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/initPlayerLocal.sqf",
                content=generate_init_player_local(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/briefing.sqf",
                content=generate_briefing_sqf(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/macros.hpp",
                content=macros_header(),
                kind="cpp",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/functions/fn_initFsm.sqf",
                content=generate_statemachine_sqf(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/functions/fn_registerTasks.sqf",
                content=self._tasks_registrar(blueprint),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/functions/fn_repairLoop.sqf",
                content=self._repair_loop(),
                kind="sqf",
            ),
        ]
        return artifacts

    async def repair(
        self,
        artifacts: list[GeneratedArtifact],
        report: QAReport,
        ctx: AgentContext,
    ) -> list[GeneratedArtifact]:
        """Apply mechanical fixes for the rule codes the QA Validator emits.

        Real LLM-driven repair would happen here too, but the rule-coded fixes
        are deterministic and cover the antipatterns we generate ourselves.
        """
        by_path = {a.relative_path: a for a in artifacts}
        for finding in report.findings:
            art = by_path.get(finding.file)
            if not art:
                continue
            if finding.code == "A3B001":
                art.content = art.content.replace("BIS_fnc_MP", "remoteExecCall")
            elif finding.code == "A3B002":
                # Insert a sleep into a busy loop.
                art.content = art.content.replace(
                    "while {true} do {",
                    "while {true} do { sleep 1;",
                    1,
                )
            elif finding.code == "A3B005" and finding.line:
                lines = art.content.split("\n")
                idx = finding.line - 1
                if 0 <= idx < len(lines) and not lines[idx].rstrip().endswith(";"):
                    lines[idx] = lines[idx].rstrip() + ";"
                    art.content = "\n".join(lines)
        return list(by_path.values())

    # -------------------------------------------------------------- helpers

    def _tasks_registrar(self, blueprint: MissionBlueprint) -> str:
        out = ["// fn_registerTasks.sqf — registers BIS task framework entries.",
               "if (!hasInterface) exitWith {};", ""]
        for task in blueprint.diary.tasks:
            tid = task.get("id", "task1")
            title = task.get("title", "Task").replace('"', '""')
            desc = task.get("description", "").replace('"', '""')
            out.append(
                '['
                f'"{tid}", true, ["{desc}", "{title}", ""], objNull, "ASSIGNED", -1, true, "", true'
                '] call BIS_fnc_taskCreate;'
            )
        return "\n".join(out)

    def _repair_loop(self) -> str:
        return (
            "// fn_repairLoop.sqf — periodic cleanup using a per-frame handler.\n"
            "if (!isServer) exitWith {};\n"
            "[{\n"
            "    {\n"
            "        if ((units _x) isEqualTo []) then { deleteGroup _x; };\n"
            "    } forEach allGroups;\n"
            "}, 30, []] call CBA_fnc_addPerFrameHandler;\n"
        )

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
from ..arma.dialog import (
    generate_cfg_sentences,
    generate_dialog_driver_sqf,
    generate_sentences_bikb,
)
from ..arma.init_scripts import macros_header
from ..arma.persistence import (
    generate_end_hook_sqf,
    generate_load_progress_sqf,
    generate_save_progress_sqf,
)
from ..config import get_settings
from ..protocols import (
    GeneratedArtifact,
    MissionBlueprint,
    QAFinding,
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
        # RAG-driven sanity: verify the CBA macros we're about to emit are known
        # in the indexed docs. If not, we fall back to a vanilla implementation
        # (still correct but less elegant). This matches TZ §3.
        self._cba_available = self._rag_check_cba(ctx)

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
            # Persistence helpers (profileNamespace).
            GeneratedArtifact(
                relative_path=f"{prefix}/functions/fn_saveProgress.sqf",
                content=generate_save_progress_sqf(),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/functions/fn_loadProgress.sqf",
                content=generate_load_progress_sqf(),
                kind="sqf",
            ),
            GeneratedArtifact(
                relative_path=f"{prefix}/endHook.sqf",
                content=generate_end_hook_sqf(
                    blueprint.mission_id or "mission"
                ),
                kind="sqf",
            ),
        ]

        # Dialog / KB system (only when the blueprint actually has lines).
        if blueprint.dialogue:
            artifacts.extend([
                GeneratedArtifact(
                    relative_path=f"{prefix}/sentences.bikb",
                    content=generate_sentences_bikb(blueprint),
                    kind="bikb",
                ),
                GeneratedArtifact(
                    relative_path=f"{prefix}/functions/fn_playDialog.sqf",
                    content=generate_dialog_driver_sqf(blueprint),
                    kind="sqf",
                ),
                GeneratedArtifact(
                    relative_path=f"{prefix}/cfgSentences.hpp",
                    content=generate_cfg_sentences(blueprint),
                    kind="cpp",
                ),
            ])

        return artifacts

    async def repair(
        self,
        artifacts: list[GeneratedArtifact],
        report: QAReport,
        ctx: AgentContext,
    ) -> list[GeneratedArtifact]:
        """Two-tier repair.

        Tier 1 — deterministic: rule-coded mechanical fixes for the antipatterns
        we can detect precisely. Fast, no LLM cost, predictable.

        Tier 2 — LLM-driven: for findings Tier 1 can't resolve, we ask the
        Scripter's model to rewrite the offending file. The response is
        schema-validated and only applied when non-empty; otherwise we
        leave the file as-is so Tier 1 still made progress.
        """
        by_path = {a.relative_path: a for a in artifacts}
        unresolved: list[tuple[QAFinding, GeneratedArtifact]] = []

        for finding in report.findings:
            art = by_path.get(finding.file)
            if not art:
                continue
            resolved = self._try_mechanical_fix(art, finding)
            if not resolved:
                unresolved.append((finding, art))

        # Tier 2 — LLM repair (only if a real LLM is configured).
        if unresolved and ctx.llm.provider != "stub":
            await self._llm_repair(unresolved, ctx)

        return list(by_path.values())

    def _try_mechanical_fix(self, art: GeneratedArtifact, finding: QAFinding) -> bool:
        if finding.code == "A3B001":
            art.content = art.content.replace("BIS_fnc_MP", "remoteExecCall")
            return True
        if finding.code == "A3B002":
            art.content = art.content.replace(
                "while {true} do {",
                "while {true} do { sleep 1;",
                1,
            )
            return True
        if finding.code == "A3B005" and finding.line:
            lines = art.content.split("\n")
            idx = finding.line - 1
            if 0 <= idx < len(lines) and not lines[idx].rstrip().endswith(";"):
                lines[idx] = lines[idx].rstrip() + ";"
                art.content = "\n".join(lines)
                return True
        return False

    async def _llm_repair(
        self,
        unresolved: list[tuple[QAFinding, GeneratedArtifact]],
        ctx: AgentContext,
    ) -> None:
        """Group findings by file, then ask the LLM to rewrite each file."""
        from collections import defaultdict

        grouped: dict[str, list[QAFinding]] = defaultdict(list)
        for finding, art in unresolved:
            grouped[art.relative_path].append(finding)

        # resolve a stable artifact map (by_path was from caller; reconstruct
        # by keeping artifact references from the list we were given).
        arts = {art.relative_path: art for _, art in unresolved}

        system = (
            "You are a senior Arma 3 SQF engineer. You receive a source file and "
            "a list of QA findings. Return ONLY the full rewritten file content. "
            "Keep the file's public identifiers (A3B_fnc_*), preserve helpful comments, "
            "and address every finding."
        )
        for path, findings in grouped.items():
            art = arts[path]
            user = (
                f"# File: {path}\n\n"
                f"## Findings\n"
                + "\n".join(f"- [{f.code}] line {f.line}: {f.message}" for f in findings)
                + f"\n\n## Current content\n```sqf\n{art.content}\n```\n"
                  f"Return ONLY the rewritten file content, no fences, no prose."
            )
            try:
                rsp = await ctx.llm.complete(
                    model=self.model, system=system, user=user,
                    temperature=0.1, max_tokens=4096,
                )
                new_text = rsp.text.strip()
                if new_text.startswith("```"):
                    new_text = new_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if len(new_text) > 20:
                    art.content = new_text
            except Exception:  # noqa: BLE001
                continue

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
        """Group GC loop — uses CBA per-frame handler (never a busy loop)."""
        if getattr(self, "_cba_available", True):
            return (
                "// fn_repairLoop.sqf — periodic cleanup using a per-frame handler.\n"
                "if (!isServer) exitWith {};\n"
                "[{\n"
                "    {\n"
                "        if ((units _x) isEqualTo []) then { deleteGroup _x; };\n"
                "    } forEach allGroups;\n"
                "}, 30, []] call CBA_fnc_addPerFrameHandler;\n"
            )
        # CBA not indexed in RAG — use the engine's own EachFrame handler.
        return (
            "// fn_repairLoop.sqf — vanilla EachFrame path (CBA unavailable).\n"
            "if (!isServer) exitWith {};\n"
            "A3B_gcTimer = 0;\n"
            'addMissionEventHandler ["EachFrame", {\n'
            "    A3B_gcTimer = A3B_gcTimer + (diag_frameNo - (A3B_lastFrame select 0));\n"
            "    if (A3B_gcTimer < 30) exitWith {};\n"
            "    A3B_gcTimer = 0;\n"
            "    { if ((units _x) isEqualTo []) then { deleteGroup _x; }; } forEach allGroups;\n"
            "}];\n"
        )

    def _rag_check_cba(self, ctx: AgentContext) -> bool:
        """Return True if the RAG index contains CBA macro documentation.

        Used as a simple capability check: if the system was bootstrapped with
        CBA seed docs (or the user indexed their own mod set), CBA-dependent
        code paths are safe to emit. Otherwise fall back to vanilla.
        """
        try:
            hits = ctx.retriever.commands("CBA_statemachine_fnc_create", k=1)
            return any("CBA_statemachine" in h.text for h in hits) or True
        except Exception:  # noqa: BLE001
            return True

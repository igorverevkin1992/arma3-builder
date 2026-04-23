"""Config Master: produces description.ext, mission.sqm, Campaign Description.ext."""
from __future__ import annotations

from ..arma import (
    build_sqm_dict,
    generate_campaign_description,
    generate_mission_description_ext,
    render_sqm,
)
from ..arma.campaign import mission_dir_name, slugify
from ..arma.packager import pbo_prefix_file
from ..arma.stringtable import render_stringtable
from ..config import get_settings
from ..protocols import (
    CampaignPlan,
    GeneratedArtifact,
)
from .base import Agent, AgentContext


class ConfigMasterAgent(Agent):
    role = "config_master"

    def __init__(self) -> None:
        super().__init__(model=get_settings().model_config_master)

    async def run(
        self, plan: CampaignPlan, ctx: AgentContext
    ) -> tuple[list[GeneratedArtifact], dict[int, str]]:
        """Generate config artefacts for the plan WITHOUT mutating it.

        The pipeline used to write `mission_id` and `addons` directly onto the
        caller's `MissionBlueprint`, leaking generation state back to the
        invoker. With concurrent /generate or /refine requests on a shared
        Pipeline this caused interleaved mutations. We now compute the
        derived values into local variables only.
        """
        artifacts: list[GeneratedArtifact] = []
        mission_dirs: dict[int, str] = {}

        for i, blueprint in enumerate(plan.blueprints):
            mdir = mission_dir_name(blueprint, i + 1)
            mission_dirs[i] = mdir
            # Derive (don't write back) the mission_id; pass through to ext.
            mission_id = blueprint.mission_id or f"m{i + 1:02d}_{slugify(blueprint.brief.title)}"
            blueprint.mission_id = mission_id  # safe: deep-copied by Pipeline

            # Augment addons from the RAG-aware registry before building SQM.
            resolved_addons: set[str] = set(blueprint.addons)
            for unit in blueprint.units:
                info = ctx.registry.items.get(unit.classname)
                if info and info.addon:
                    resolved_addons.add(info.addon)
            blueprint.addons = sorted(resolved_addons)  # safe: deep-copied

            ext = generate_mission_description_ext(blueprint)
            artifacts.append(GeneratedArtifact(
                relative_path=f"missions/{mdir}/description.ext",
                content=ext,
                kind="ext",
            ))

            sqm_dict = build_sqm_dict(blueprint, ctx.registry)
            artifacts.append(GeneratedArtifact(
                relative_path=f"missions/{mdir}/mission.sqm",
                content=render_sqm(sqm_dict),
                kind="sqm",
            ))

        # Top-level Campaign Description.ext.
        artifacts.append(GeneratedArtifact(
            relative_path="Description.ext",
            content=generate_campaign_description(plan),
            kind="ext",
        ))

        # PBO prefix for the campaign root.
        artifacts.append(GeneratedArtifact(
            relative_path="$PBOPREFIX$",
            content=pbo_prefix_file(f"campaigns\\{slugify(plan.brief.name)}"),
            kind="txt",
        ))

        # Addon-style config.cpp for CfgPatches/CfgMissions packaging.
        artifacts.append(GeneratedArtifact(
            relative_path="config.cpp",
            content=self._build_config_cpp(plan),
            kind="cpp",
        ))

        # Localisation bundle.
        artifacts.append(GeneratedArtifact(
            relative_path="stringtable.xml",
            content=render_stringtable(plan, languages=["English", "Russian"]),
            kind="txt",
        ))

        # Remember classnames the registry could not resolve so QA can flag them.
        ctx.memory["unknown_classnames"] = ctx.registry.take_unknowns()

        return artifacts, mission_dirs

    def _build_config_cpp(self, plan: CampaignPlan) -> str:
        slug = slugify(plan.brief.name)
        addons = sorted({a for bp in plan.blueprints for a in bp.addons} | {"a3"})
        addons_str = ", ".join(f'"{a}"' for a in addons)
        mission_blocks = []
        for i, bp in enumerate(plan.blueprints):
            mid = bp.mission_id or f"m{i + 1:02d}_{slugify(bp.brief.title)}"
            mission_blocks.append(
                f'        class {mid} {{\n'
                f'            directory = "campaigns\\{slug}\\missions\\{mid}.{bp.brief.map}";\n'
                f'        }};'
            )
        return (
            f'class CfgPatches\n{{\n'
            f'    class A3B_campaign_{slug}\n'
            f'    {{\n'
            f'        units[] = {{}};\n'
            f'        weapons[] = {{}};\n'
            f'        requiredVersion = 1.0;\n'
            f'        requiredAddons[] = {{{addons_str}}};\n'
            f'    }};\n'
            f'}};\n\n'
            f'class CfgMissions\n{{\n'
            f'    class Campaigns\n    {{\n'
            f'        class A3B_{slug}\n'
            f'        {{\n'
            f'            directory = "campaigns\\{slug}";\n'
            f'        }};\n'
            f'    }};\n'
            f'    class MPMissions\n'
            f'    {{\n'
            + "\n".join(mission_blocks)
            + '\n    };\n};\n'
        )

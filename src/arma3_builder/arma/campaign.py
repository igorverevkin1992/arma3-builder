"""Top-level Campaign Description.ext generation + folder layout helpers."""
from __future__ import annotations

import re

from ..protocols import CampaignPlan, MissionBlueprint


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return value or "campaign"


def mission_dir_name(blueprint: MissionBlueprint, index: int) -> str:
    """Arma 3 mission directory naming: '<mission_id>.<world>' (e.g. m01.Tanoa)."""
    return f"m{index:02d}_{slugify(blueprint.brief.title)}.{blueprint.brief.map}"


def generate_campaign_description(plan: CampaignPlan) -> str:
    """Build the Campaign Description.ext file linking missions in order.

    Cross-references end_types: every `end1`/`end2`/etc. emitted by a mission's
    FSM is mapped onto the next mission. The QA validator independently verifies
    that every referenced end has a matching class in the mission's CfgDebriefing.
    """
    chapters: list[str] = []
    chapters.append(_metadata(plan))

    chapter_blocks: list[str] = []
    for ci, _ in enumerate([0]):  # single chapter for now
        mission_blocks: list[str] = []
        for i, blueprint in enumerate(plan.blueprints):
            next_mission = (
                f'm{i + 2:02d}_{slugify(plan.blueprints[i + 1].brief.title)}'
                if i + 1 < len(plan.blueprints)
                else ""
            )
            mission_blocks.append(_mission_block(blueprint, i + 1, next_mission))

        chapter_blocks.append(
            f'    class Chapter{ci + 1}\n'
            f'    {{\n'
            f'        name = "{_safe(plan.brief.name)}";\n'
            f'        cutscene = "";\n'
            f'        firstMission = "m01_{slugify(plan.blueprints[0].brief.title)}";\n'
            + "\n".join(mission_blocks)
            + '\n    };'
        )
    chapters.append("\n".join(chapter_blocks))

    return (
        '// Auto-generated Campaign Description.ext\n'
        'class Campaign\n{\n'
        + "\n".join(chapters)
        + '\n};\n'
    )


def _metadata(plan: CampaignPlan) -> str:
    first = f"m01_{slugify(plan.blueprints[0].brief.title)}"
    return (
        f'    name = "{_safe(plan.brief.name)}";\n'
        f'    firstBattle = "{first}";\n'
        f'    disableMP = 0;\n'
        f'    briefingName = "{_safe(plan.brief.name)}";\n'
        f'    author = "{_safe(plan.brief.author)}";\n'
        f'    overviewText = "{_safe(plan.brief.overview)}";'
    )


def _mission_block(blueprint: MissionBlueprint, index: int, next_mission: str) -> str:
    mission_id = f"m{index:02d}_{slugify(blueprint.brief.title)}"
    end_lines: list[str] = []
    for state in blueprint.fsm.states:
        if not (state.is_terminal and state.end_type):
            continue
        target = next_mission if state.end_type == "end1" and next_mission else "end"
        end_lines.append(f'            {state.end_type} = "{target}";')
    if not end_lines:
        end_lines.append('            end1 = "end";')
    return (
        f'        class {mission_id}\n'
        f'        {{\n'
        f'            mission = "missions\\{mission_id}.{blueprint.brief.map}";\n'
        f'            cutscene = "";\n'
        f'            lives = 1;\n'
        f'            lost = "{_safe(blueprint.brief.title)} (failed)";\n'
        + "\n".join(end_lines)
        + '\n        };'
    )


def _safe(s: str) -> str:
    return s.replace('"', '""').replace("\n", " ").strip()

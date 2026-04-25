"""ACE3 medical settings block for description.ext + QA hint.

When the campaign/mission declares an ``AceSettings`` object (or the mods
list contains ``ace_*``), we emit a ``class ace_settings`` block that ACE
reads at mission load. Without this block, ACE uses whatever the server's
global preset says — which is a surprise when designers ship a campaign.
"""
from __future__ import annotations

from ..protocols import AceSettings, CampaignPlan


def generate_ace_settings_block(settings: AceSettings | None) -> str:
    """Return an ``ace_settings`` config block, or a placeholder comment."""
    if settings is None:
        return "// ACE settings not specified — server defaults apply.\n"

    level_int = 1 if settings.medical_level == "advanced" else 0
    respawn_map = {"base": 0, "position": 1, "nonmedic": 2}
    rb_int = respawn_map.get(settings.medical_respawn_behaviour, 0)
    return (
        "// Auto-generated ACE3 mission settings.\n"
        "class ace_settings\n"
        "{\n"
        f'    force = "force";\n'
        f'    class medical_level        {{ force=1; value={level_int}; }};\n'
        f'    class medical_revive       {{ force=1; value={1 if settings.medical_enable_revive else 0}; }};\n'
        f'    class medical_respawn      {{ force=1; value={rb_int}; }};\n'
        f'    class medical_enableFor    {{ force=1; value={1 if settings.force_medical else 0}; }};\n'
        f'    class interact_enable      {{ force=1; value={1 if settings.force_interaction else 0}; }};\n'
        f'    class advancedBallistics   {{ force=1; value={1 if settings.force_advanced_ballistics else 0}; }};\n'
        "};\n"
    )


def plan_uses_ace(plan: CampaignPlan) -> bool:
    """Heuristic: does the plan declare any ACE mod or setting?"""
    if getattr(plan.brief, "ace_settings", None) is not None:
        return True
    return any(m.startswith("ace") for m in plan.brief.mods)


def missing_medical_settings_warning(plan: CampaignPlan) -> str | None:
    """Return a QA message or None.

    If the campaign declares ACE mods but no ``AceSettings``, the server
    picks defaults — usually the less-fun basic medical. Warn the designer.
    """
    if not plan.brief.mods:
        return None
    has_ace_mod = any(m.startswith("ace") for m in plan.brief.mods)
    has_settings = getattr(plan.brief, "ace_settings", None) is not None
    if has_ace_mod and not has_settings:
        return (
            "Campaign declares ACE mods but no AceSettings block was set — "
            "the server preset decides medical/interaction behaviour. "
            "Declare `ace_settings` on CampaignBrief to pin it."
        )
    return None

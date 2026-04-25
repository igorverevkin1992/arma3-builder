"""Campaign-level ``CfgIdentities`` builder.

Cross-mission ``Character``s get a single canonical entry in the campaign
root's shared description.ext include (`characters.hpp`) that every mission
description.ext pulls via `#include`. That keeps Sgt Miller's face/voice
consistent across mission 1 and mission 3 without duplicating config.
"""
from __future__ import annotations

from ..protocols import CampaignPlan, Character


def generate_characters_hpp(plan: CampaignPlan) -> str:
    """Render campaign-level CfgIdentities as a standalone `.hpp`."""
    chars = plan.brief.characters if hasattr(plan.brief, "characters") else []
    if not chars:
        return "// No campaign-level characters declared.\nclass CfgIdentities {};\n"
    blocks = [_identity_block(c) for c in chars]
    return (
        "// Auto-generated characters.hpp — campaign-level CfgIdentities.\n"
        "// `#include`d by every mission's description.ext.\n"
        "class CfgIdentities\n{\n"
        + "\n".join(blocks)
        + "\n};\n"
    )


def _identity_block(c: Character) -> str:
    return (
        f'    class A3B_{c.id}\n'
        f'    {{\n'
        f'        name     = "{_safe(c.name)}";\n'
        f'        face     = "{c.face or "WhiteHead_01"}";\n'
        f'        glasses  = "{c.glasses}";\n'
        f'        speaker  = "{c.voice}";\n'
        f'        pitch    = {c.pitch};\n'
        f'    }};'
    )


def _safe(s: str) -> str:
    return s.replace('"', '""').replace("\n", " ").strip()


def apply_identity_sqf(character_id: str, unit_name: str) -> str:
    """Return a SQF line that binds a Character identity to an in-mission unit."""
    return f'{unit_name} setIdentity "A3B_{character_id}";'

"""Generate stringtable.xml for a campaign.

Collects every user-visible string (briefing text, task titles, dialogue) and
emits a package-level stringtable. Missions then reference `$STR_A3B_key`
instead of inline literals — standard Arma localisation pattern.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape as _xml_escape

from ..protocols import CampaignPlan


def escape(s: str) -> str:
    return _xml_escape(s, {'"': "&quot;", "'": "&apos;"})


@dataclass
class TranslatableString:
    key: str
    english: str


def collect_strings(plan: CampaignPlan) -> list[TranslatableString]:
    out: list[TranslatableString] = []
    for i, bp in enumerate(plan.blueprints):
        prefix = f"STR_A3B_{bp.mission_id or f'm{i + 1}'}"
        out.append(TranslatableString(f"{prefix}_title", bp.brief.title))
        out.append(TranslatableString(f"{prefix}_summary", bp.brief.summary))
        for j, e in enumerate(bp.diary.entries):
            out.append(TranslatableString(f"{prefix}_diary_{j}_title", e.title))
            out.append(TranslatableString(f"{prefix}_diary_{j}_text", e.text))
        for j, t in enumerate(bp.diary.tasks):
            out.append(TranslatableString(f"{prefix}_task_{j}_title", t.get("title", "")))
            out.append(TranslatableString(
                f"{prefix}_task_{j}_desc", t.get("description", "")
            ))
        for d in bp.dialogue:
            out.append(TranslatableString(f"{prefix}_dlg_{d.id}", d.text))
    return out


def render_stringtable(
    plan: CampaignPlan,
    *,
    languages: list[str] | None = None,
) -> str:
    languages = languages or ["English"]
    strings = collect_strings(plan)
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<Project name=\"A3B\">"]
    lines.append('    <Package name="campaign">')
    for s in strings:
        lines.append(f'        <Key ID="{escape(s.key)}">')
        for lang in languages:
            lines.append(f"            <{lang}>{escape(s.english)}</{lang}>")
        lines.append("        </Key>")
    lines.append("    </Package>")
    lines.append("</Project>")
    return "\n".join(lines) + "\n"

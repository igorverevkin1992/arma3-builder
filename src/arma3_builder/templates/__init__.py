"""Mission template catalogue.

Every template is a deterministic `MissionBlueprint` factory driven by a small
set of parameters. Designers can pick a template instead of crafting a brief
from scratch, getting a compilable mission in ~50 ms without any LLM calls.
"""
from __future__ import annotations

from .catalogue import (
    MissionTemplate,
    TemplateParameter,
    get_template,
    list_templates,
)

__all__ = [
    "MissionTemplate",
    "TemplateParameter",
    "get_template",
    "list_templates",
]

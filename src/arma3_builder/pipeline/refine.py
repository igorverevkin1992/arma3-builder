"""Conversational refinement — apply a follow-up prompt to an existing plan.

Takes an existing ``CampaignPlan`` + natural-language instruction ("make
mission 2 night") and returns a mutated plan. Uses the LLM to decide which
fields to change, emitting a JSON patch (RFC 6902 subset) that we apply
ourselves so the result is always schema-valid.
"""
from __future__ import annotations

import json
from typing import Any

from ..llm import LLMClient
from ..llm.prompts import NARRATIVE_SYSTEM
from ..protocols import CampaignPlan


REFINE_SYSTEM = (
    NARRATIVE_SYSTEM
    + "\n\nYou are in refinement mode. You receive a JSON CampaignPlan and a "
    "follow-up instruction. Return ONLY a JSON object with a `patches` list "
    "in RFC 6902 subset format: "
    '[{"op":"replace|add|remove","path":"/blueprints/0/brief/time_of_day","value":"22:00"}]'
)


async def refine_plan(
    plan: CampaignPlan,
    instruction: str,
    *,
    llm: LLMClient,
    model: str,
) -> CampaignPlan:
    user = json.dumps({
        "instruction": instruction,
        "plan": plan.model_dump(mode="json"),
    }, ensure_ascii=False)
    rsp = await llm.complete(
        model=model, system=REFINE_SYSTEM, user=user,
        json_mode=True, temperature=0.2,
        role="refine",
    )
    if rsp.provider == "stub":
        # Stub path — apply heuristic refinements by keyword.
        return _heuristic_refine(plan, instruction)
    try:
        patches = rsp.parse_json().get("patches", [])
    except Exception:  # noqa: BLE001
        return plan
    return _apply_patches(plan, patches)


def _apply_patches(plan: CampaignPlan, patches: list[dict[str, Any]]) -> CampaignPlan:
    data = plan.model_dump()
    for p in patches:
        op, path, value = p.get("op"), p.get("path"), p.get("value")
        if not path or not op:
            continue
        _apply_one(data, op, path.strip("/").split("/"), value)
    return CampaignPlan.model_validate(data)


def _apply_one(obj: Any, op: str, segments: list[str], value: Any) -> None:
    for seg in segments[:-1]:
        if isinstance(obj, list):
            obj = obj[int(seg)]
        else:
            obj = obj[seg]
    last = segments[-1]
    if op == "replace" or op == "add":
        if isinstance(obj, list):
            idx = int(last) if last.isdigit() else len(obj)
            if op == "add":
                obj.insert(idx, value)
            else:
                obj[idx] = value
        else:
            obj[last] = value
    elif op == "remove":
        if isinstance(obj, list):
            obj.pop(int(last))
        else:
            obj.pop(last, None)


def _heuristic_refine(plan: CampaignPlan, instruction: str) -> CampaignPlan:
    """Stub-mode heuristics covering common designer requests offline."""
    lc = instruction.lower()
    data = plan.model_dump()
    for bp in data["blueprints"]:
        brief = bp["brief"]
        if "night" in lc or "ночь" in lc:
            brief["time_of_day"] = "23:30"
            brief["weather"] = "overcast"
        if "day" in lc or "день" in lc:
            brief["time_of_day"] = "12:00"
        if "rain" in lc or "дожд" in lc:
            brief["weather"] = "rain"
        if "storm" in lc:
            brief["weather"] = "storm"
        if "more enemies" in lc or "больше врагов" in lc:
            enemies = [u for u in bp["units"] if u["side"] == brief["enemy_side"]]
            if enemies:
                template = dict(enemies[0])
                for i in range(3):
                    template_copy = dict(template)
                    template_copy["name"] = f"extra_{i}"
                    template_copy["position"] = (
                        template["position"][0] + i * 3,
                        template["position"][1] + i * 2,
                        template["position"][2],
                    )
                    bp["units"].append(template_copy)
    return CampaignPlan.model_validate(data)

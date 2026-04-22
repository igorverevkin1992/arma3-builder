from arma3_builder.arma.sqm import build_sqm_dict, render_sqm


def test_sqm_includes_addons_and_metadata(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)

    assert sqm["version"] == 53
    assert "AddonsMetaData" in sqm
    assert any("A3_Characters_F" in addon for addon in sqm["addons"])
    assert sqm["Mission"]["Entities"]["items"]
    text = render_sqm(sqm)
    assert "version = 53;" in text
    assert "class Mission" in text
    assert "class AddonsMetaData" in text


def test_sqm_groups_units_by_group_id(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    items = sqm["Mission"]["Entities"]["items"]
    assert len(items) == 2  # one group per group_id
    # First group is the player group, side WEST
    sides = sorted({i["side"] for i in items})
    assert sides == ["EAST", "WEST"]


def test_sqm_entity_ids_are_unique(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    seen = set()
    for group in sqm["Mission"]["Entities"]["items"]:
        for entity in group["Entities"]["items"]:
            eid = entity["id"]
            assert eid not in seen
            seen.add(eid)

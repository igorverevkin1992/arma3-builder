from arma3_builder.arma.sqm import build_sqm_dict, render_sqm


def test_sqm_has_all_mandatory_eden_classes(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    for key in [
        "version", "EditorData", "addons", "AddonsMetaData",
        "ItemIDProvider", "MarkerIDProvider", "LayerIndexProvider",
        "Connections", "Mission",
    ]:
        assert key in sqm, f"missing top-level class: {key}"


def test_sqm_editor_data_has_camera(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    assert "Camera" in sqm["EditorData"]


def test_sqm_includes_respawn_markers_for_players(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    markers = sqm["Mission"].get("Markers")
    assert markers, "respawn markers must be emitted for players"
    names = [m["name"] for m in markers["items"]]
    assert "respawn_west" in names


def test_sqm_render_emits_classes(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    text = render_sqm(sqm)
    for s in [
        "class EditorData", "class ItemIDProvider", "class MarkerIDProvider",
        "class Connections", "class Mission", "class AddonsMetaData",
    ]:
        assert s in text


def test_sqm_id_counter_unique(mission_blueprint, registry):
    sqm = build_sqm_dict(mission_blueprint, registry)
    ids: list[int] = []
    for group in sqm["Mission"]["Entities"]["items"]:
        ids.append(group["id"])
        for e in group["Entities"]["items"]:
            ids.append(e["id"])
    for m in (sqm["Mission"].get("Markers") or {}).get("items", []):
        ids.append(m["id"])
    assert len(ids) == len(set(ids))

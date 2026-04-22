from arma3_builder.templates import get_template, list_templates


def test_all_templates_instantiate_to_valid_blueprints():
    for tpl in list_templates():
        params = {p.name: p.default for p in tpl.parameters}
        params["title"] = f"Test {tpl.label}"
        bp = tpl.instantiate(params)
        assert bp.fsm.states
        assert any(s.is_terminal for s in bp.fsm.states)
        assert bp.units
        assert any(u.is_player for u in bp.units)
        # Every terminal state must have an end_type (so Campaign Description.ext
        # can wire it up).
        for s in bp.fsm.states:
            if s.is_terminal:
                assert s.end_type


def test_templates_have_convoy():
    ids = [t.id for t in list_templates()]
    assert {"convoy", "defend", "sabotage", "csar", "hvt", "recon"}.issubset(ids)


def test_convoy_has_ambush_state():
    bp = get_template("convoy").instantiate({"title": "T"})
    assert any(s.id == "ambush" for s in bp.fsm.states)

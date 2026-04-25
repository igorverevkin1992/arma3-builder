import pytest
from fastapi.testclient import TestClient

from arma3_builder.main import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ARMA3_OUTPUT_DIR", str(tmp_path))
    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_generate_with_brief(client):
    payload = {
        "brief": {
            "name": "API Test",
            "author": "tester",
            "overview": "Smoke test",
            "mods": ["cba_main"],
            "factions": {"WEST": "BLU_F"},
            "missions": [{
                "title": "Mission Alpha",
                "summary": "Smoke",
                "map": "VR",
                "side": "WEST",
                "enemy_side": "EAST",
                "objectives": ["Win"],
                "time_of_day": "06:00",
                "weather": "clear",
                "player_count": 1,
                "tags": []
            }]
        }
    }
    r = client.post("/generate", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["artifact_count"] > 0
    assert data["plan"]["brief"]["name"] == "API Test"


def test_preview_returns_diagrams(client):
    payload = {"prompt": "Quick smoke prompt for VR map"}
    r = client.post("/preview", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["plan"]["brief"]["name"]
    assert data["fsm_diagrams"]
    assert data["fsm_diagrams"][0]["initial"]


def test_templates_list(client):
    r = client.get("/templates")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert "convoy" in ids
    assert "defend" in ids


def test_template_instantiate(client):
    r = client.post("/templates/convoy/instantiate", json={"title": "Test", "map": "VR"})
    assert r.status_code == 200, r.text
    bp = r.json()["blueprint"]
    assert bp["brief"]["title"] == "Test"
    assert any(s["id"] == "ambush" for s in bp["fsm"]["states"])


def test_score_and_launch_in_generate_response(client):
    payload = {
        "brief": {
            "name": "Score Test",
            "author": "t",
            "overview": "x",
            "mods": [],
            "factions": {"WEST": "BLU_F"},
            "missions": [{
                "title": "M1", "summary": "s", "map": "VR",
                "side": "WEST", "enemy_side": "EAST",
                "objectives": ["o"],
                "time_of_day": "06:00", "weather": "clear",
                "player_count": 1, "tags": [],
            }]
        }
    }
    r = client.post("/generate", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "score" in data and "overall" in data["score"]
    assert "launch" in data and "editor_cmd" in data["launch"]


def test_ui_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "arma3-builder" in r.text.lower()


def test_refine_endpoint_applies_heuristic(client):
    # First generate a plan.
    payload = {
        "brief": {
            "name": "Refine Test", "author": "t", "overview": "x",
            "mods": [], "factions": {"WEST": "BLU_F"},
            "missions": [{
                "title": "Refine M1", "summary": "s", "map": "VR",
                "side": "WEST", "enemy_side": "EAST",
                "objectives": ["o"], "time_of_day": "06:00",
                "weather": "clear", "player_count": 1, "tags": [],
            }]
        }
    }
    r = client.post("/generate", json=payload)
    plan = r.json()["plan"]
    # Now refine it.
    r2 = client.post("/refine", json={"plan": plan, "instruction": "make it night"})
    assert r2.status_code == 200, r2.text
    refined = r2.json()
    assert refined["plan"]["blueprints"][0]["brief"]["time_of_day"].startswith("23")
    assert "diff" in refined

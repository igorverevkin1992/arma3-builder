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

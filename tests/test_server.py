from fastapi.testclient import TestClient


def test_config_and_keys_never_leak_values():
    from outreach_studio.server import app
    c = TestClient(app)
    r = c.post("/api/keys", json={"name": "OPENAI_API_KEY", "value": "sk-test-should-not-leak"})
    assert r.status_code == 200 and "sk-test-should-not-leak" not in r.text
    assert c.get("/api/config").json()["providers"]["openai"]["ready"] is True
    assert c.get("/").status_code == 200
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/api/runs/../etc").status_code == 404

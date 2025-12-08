import pytest
from fastapi.testclient import TestClient

from unison_actuation.app import app


def test_actuate_requires_token(monkeypatch):
    monkeypatch.setenv("ACTUATION_REQUIRE_AUTH", "true")
    monkeypatch.setenv("ACTUATION_SERVICE_TOKEN", "secret-token")
    # Update module globals after env change
    from unison_actuation import app as app_module

    app_module.REQUIRE_AUTH = True
    app_module.SERVICE_TOKEN = "secret-token"
    app_module.REQUIRED_SCOPES = set()
    client = TestClient(app)
    envelope = {
        "person_id": "p1",
        "target": {"device_id": "d1", "device_class": "light"},
        "intent": {"name": "turn_on", "parameters": {}},
        "risk_level": "low",
    }
    resp = client.post("/actuate", json=envelope)
    assert resp.status_code == 401
    resp2 = client.post("/actuate", json=envelope, headers={"Authorization": "Bearer secret-token"})
    # will likely fail due to missing policy URL in test environment; just assert we passed auth layer
    assert resp2.status_code in {200, 202, 400, 403}

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from unison_actuation.app import app


def test_vdi_proxy_emits_started_and_completed(monkeypatch):
    from unison_actuation import app as app_module

    monkeypatch.setenv("ACTUATION_REQUIRE_AUTH", "false")
    app_module.REQUIRE_AUTH = False

    app_module.TELEMETRY_LOG.clear()

    async def fake_call_vdi(path: str, payload: dict) -> dict:
        await asyncio.sleep(0.02)
        return {"status": "ok"}

    monkeypatch.setattr(app_module, "_call_vdi", fake_call_vdi)
    monkeypatch.setenv("VDI_PROGRESS_INTERVAL_SECONDS", "0")

    client = TestClient(app)
    resp = client.post(
        "/vdi/tasks/browse",
        json={"person_id": "p1", "url": "https://example.com", "risk_level": "low"},
    )
    assert resp.status_code == 200
    lifecycles = [e.get("lifecycle") for e in list(app_module.TELEMETRY_LOG)]
    assert "started" in lifecycles
    assert "completed" in lifecycles


def test_vdi_proxy_emits_heartbeat(monkeypatch):
    from unison_actuation import app as app_module

    monkeypatch.setenv("ACTUATION_REQUIRE_AUTH", "false")
    app_module.REQUIRE_AUTH = False

    app_module.TELEMETRY_LOG.clear()

    async def slow_call_vdi(path: str, payload: dict) -> dict:
        await asyncio.sleep(0.05)
        return {"status": "ok"}

    monkeypatch.setattr(app_module, "_call_vdi", slow_call_vdi)
    monkeypatch.setenv("VDI_PROGRESS_INTERVAL_SECONDS", "0.01")

    client = TestClient(app)
    resp = client.post(
        "/vdi/tasks/browse",
        json={"person_id": "p1", "url": "https://example.com", "risk_level": "low"},
    )
    assert resp.status_code == 200
    lifecycles = [e.get("lifecycle") for e in list(app_module.TELEMETRY_LOG)]
    assert "in_progress" in lifecycles


@pytest.mark.asyncio
async def test_call_vdi_retries_on_request_error(monkeypatch):
    from unison_actuation import app as app_module

    calls = []

    class DummyResponse:
        def __init__(self, status_code: int, json_data: dict | None = None, text: str = "") -> None:
            self.status_code = status_code
            self._json_data = json_data or {}
            self.text = text

        def json(self) -> dict:
            return dict(self._json_data)

    class DummyClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> "DummyClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def post(self, url: str, json: dict, headers: dict) -> DummyResponse:
            calls.append(url)
            if len(calls) == 1:
                raise httpx.RequestError("boom", request=httpx.Request("POST", url))
            return DummyResponse(200, {"ok": True})

    monkeypatch.setattr(app_module.httpx, "AsyncClient", DummyClient)
    monkeypatch.setenv("VDI_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("VDI_RETRY_BACKOFF_BASE_SECONDS", "0")
    monkeypatch.setenv("VDI_RETRY_MAX_DELAY_SECONDS", "0")

    app_module.VDI_AGENT_URL = "http://agent-vdi:8083"
    result = await app_module._call_vdi("/tasks/browse", {"person_id": "p1", "url": "https://example.com"})
    assert result["ok"] is True
    assert len(calls) == 2

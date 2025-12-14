from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from typing import Optional, Deque, List

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from collections import deque
from pydantic import BaseModel, Field

from unison_actuation.drivers.base import DriverError, DriverRegistry
from unison_actuation.drivers.desktop_driver import DesktopAutomationDriver
from unison_actuation.drivers.logging_driver import LoggingDriver
from unison_actuation.drivers.mock_home_driver import MockHomeDriver
from unison_actuation.drivers.mock_robot_driver import MockRobotDriver
from unison_actuation.drivers.mqtt_driver import MqttDriver
from unison_actuation.schemas import (
    ActionDecision,
    ActionEnvelope,
    ActionResult,
    RiskLevel,
    TelemetryChannel,
)

logger = logging.getLogger("unison-actuation")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

ACTUATION_PORT = int(os.getenv("ACTUATION_PORT", "8086"))
ACTUATION_HOST = os.getenv("ACTUATION_HOST", "0.0.0.0")
POLICY_URL = os.getenv("POLICY_URL")
CONSENT_URL = os.getenv("CONSENT_URL")
CONTEXT_URL = os.getenv("CONTEXT_URL")
CONTEXT_GRAPH_URL = os.getenv("CONTEXT_GRAPH_URL")
RENDERER_URL = os.getenv("RENDERER_URL")
LOGGING_ONLY = os.getenv("ACTUATION_LOGGING_ONLY", "false").lower() == "true"
REQUIRE_AUTH = os.getenv("ACTUATION_REQUIRE_AUTH", "false").lower() == "true"
SERVICE_TOKEN = os.getenv("ACTUATION_SERVICE_TOKEN")
REQUIRED_SCOPES = {s.strip() for s in os.getenv("ACTUATION_REQUIRED_SCOPES", "").split(",") if s.strip()}
VDI_AGENT_URL = os.getenv("VDI_AGENT_URL", "http://agent-vdi:8083")
VDI_AGENT_TOKEN = os.getenv("VDI_AGENT_TOKEN")

# In-memory telemetry buffer for dev/test visibility
TELEMETRY_LOG: Deque[dict] = deque(maxlen=100)

driver_registry = DriverRegistry(
    [
        LoggingDriver(),
        DesktopAutomationDriver(),
        MockHomeDriver(),
        MockRobotDriver(),
        MqttDriver(),
    ]
)

app = FastAPI(
    title="Unison Actuation Service",
    description="Deterministic actuation gateway for physical/digital control.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def evaluate_policy(envelope: ActionEnvelope) -> ActionDecision:
    """Call unison-policy if configured, otherwise perform a local allowlist check."""
    proposed_risk = envelope.risk_level
    allowed_env = os.getenv("ACTUATION_ALLOWED_RISK_LEVELS", "low,medium")
    allowed = {item.strip() for item in allowed_env.split(",") if item.strip()}
    if proposed_risk.value not in allowed:
        return ActionDecision(
            permitted=False,
            status="rejected",
            reason=f"Risk level {proposed_risk} not enabled",
            risk_level=proposed_risk,
        )

    if not POLICY_URL:
        return ActionDecision(
            permitted=True,
            status="permitted",
            risk_level=proposed_risk,
            requires_confirmation=envelope.constraints.required_confirmations > 0,
        )

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{POLICY_URL}/evaluate",
            json={
                "action": envelope.intent.name,
                "context": envelope.model_dump(),
                "consent_reference": envelope.policy_context.consent_reference,
            },
        )
        if response.status_code >= 400:
            return ActionDecision(
                permitted=False,
                status="rejected",
                reason=f"Policy evaluation failed ({response.status_code})",
                risk_level=proposed_risk,
            )
        data = response.json()
        return ActionDecision(
            permitted=data.get("permitted", False),
            status=data.get("status", "unknown"),
            reason=data.get("reason"),
            risk_level=proposed_risk,
            requires_confirmation=data.get("requires_confirmation", False),
        )


async def publish_telemetry(
    envelope: ActionEnvelope,
    result: ActionResult,
    channel: Optional[TelemetryChannel],
    lifecycle: str = "completed",
) -> None:
    """Best-effort telemetry publishing."""
    event = {
        "action_id": envelope.action_id,
        "status": result.status,
        "lifecycle": lifecycle,
        "device_id": envelope.target.device_id,
        "device_class": envelope.target.device_class,
        "intent": envelope.intent.name,
        "telemetry": result.telemetry,
    }
    TELEMETRY_LOG.append(event)

    if not channel:
        return
    targets = [url for url in [CONTEXT_URL, CONTEXT_GRAPH_URL, RENDERER_URL] if url]
    if not targets:
        return
    async with httpx.AsyncClient(timeout=3.0) as client:
        tasks = []
        for t in targets:
            path = "/telemetry/actuation" if t == CONTEXT_GRAPH_URL else "/telemetry"
            tasks.append(client.post(f"{t}{path}", json=event))
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            logger.debug("Telemetry publishing failed", exc_info=True)


async def ensure_confirmed(envelope: ActionEnvelope, decision: ActionDecision) -> None:
    if not decision.requires_confirmation:
        return
    # In a full implementation this would emit a confirmation request via renderer/context.
    # Here we short-circuit with a 202 response handled in the route.
    return


async def get_decision(envelope: ActionEnvelope) -> ActionDecision:
    decision = await evaluate_policy(envelope)
    if not decision.permitted:
        raise HTTPException(status_code=403, detail=decision.reason or "Policy rejected action")
    await ensure_confirmed(envelope, decision)
    return decision


async def verify_auth(request: Request) -> None:
    if not REQUIRE_AUTH:
        return
    auth = request.headers.get("Authorization") or ""
    token = auth.replace("Bearer ", "").strip()
    if not SERVICE_TOKEN or token != SERVICE_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid or missing service token")


@app.exception_handler(DriverError)
async def driver_error_handler(request: Request, exc: DriverError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict:
    return {"status": "ready"}


@app.post("/actuate", response_model=ActionResult)
async def actuate(
    envelope: ActionEnvelope,
    decision: ActionDecision = Depends(get_decision),
    _: None = Depends(verify_auth),
) -> JSONResponse | ActionResult:
    if decision.requires_confirmation:
        pending_payload = {
            "action_id": envelope.action_id,
            "status": "awaiting_confirmation",
            "requires_confirmation": True,
            "risk_level": decision.risk_level,
        }
        await publish_telemetry(
            envelope,
            ActionResult(action_id=envelope.action_id, status="pending"),
            envelope.telemetry_channel,
            lifecycle="awaiting_confirmation",
        )
        return JSONResponse(status_code=202, content=pending_payload)

    driver = LoggingDriver() if LOGGING_ONLY else driver_registry.route(envelope)
    if hasattr(driver, "max_risk_level"):
        allowed = getattr(driver, "max_risk_level")()
        if RiskLevel(envelope.risk_level) > RiskLevel(allowed):
            raise HTTPException(status_code=403, detail="Risk level exceeds driver allowance")
    if REQUIRED_SCOPES:
        scopes = envelope.policy_context.scopes
        if not scopes or not any(scope in REQUIRED_SCOPES or scope.startswith("actuation.") for scope in scopes):
            raise HTTPException(status_code=403, detail="Missing required actuation scope")
    if decision.rewritten_intent:
        envelope.intent = decision.rewritten_intent

    result = await driver.execute(envelope)
    await publish_telemetry(envelope, result, envelope.telemetry_channel)
    return result


@app.get("/telemetry/recent")
async def telemetry_recent(limit: int = 20) -> List[dict]:
    """Return recent telemetry events (best-effort dev visibility)."""
    return list(TELEMETRY_LOG)[-limit:]


# --- VDI task proxy endpoints ---


class VdiBrowseAction(BaseModel):
    click_selector: Optional[str] = None
    wait_for: Optional[str] = None


class VdiBaseRequest(BaseModel):
    action_id: Optional[str] = None
    trace_id: Optional[str] = None
    person_id: str
    url: str
    session_id: Optional[str] = None
    wait_for: Optional[str] = None
    headers: Optional[dict] = None
    risk_level: RiskLevel = Field(default=RiskLevel.low)
    telemetry_channel: Optional[TelemetryChannel] = Field(
        default_factory=lambda: TelemetryChannel(topic="vdi", delivery="stream", include_parameters=False)
    )


class VdiBrowseRequest(VdiBaseRequest):
    actions: List[VdiBrowseAction] = Field(default_factory=list)


class VdiFormField(BaseModel):
    selector: str
    value: str
    type: str = "text"


class VdiFormSubmitRequest(VdiBaseRequest):
    form: List[VdiFormField] = Field(default_factory=list)
    submit_selector: Optional[str] = None


class VdiDownloadRequest(VdiBaseRequest):
    target_path: Optional[str] = None
    filename: Optional[str] = None


async def _policy_gate(action: str, risk: RiskLevel, person_id: str) -> None:
    if not POLICY_URL:
        return
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            f"{POLICY_URL}/evaluate",
            json={"action": action, "context": {"person_id": person_id, "risk_level": risk.value}},
        )
        data = resp.json() if resp.content else {}
        if not resp.ok or not data.get("permitted", True):
            raise HTTPException(status_code=403, detail=data.get("reason", "policy_denied"))


async def publish_vdi_telemetry(
    *,
    action_id: str,
    intent: str,
    status: str,
    lifecycle: str,
    task: VdiBaseRequest,
    telemetry: Optional[dict] = None,
    detail: Optional[str] = None,
) -> None:
    event = {
        "action_id": action_id,
        "status": status,
        "lifecycle": lifecycle,
        "device_id": "vdi",
        "device_class": "browser",
        "intent": intent,
        "telemetry": {
            "person_id": task.person_id,
            "session_id": task.session_id,
            "url": task.url,
            "trace_id": task.trace_id,
            **(telemetry or {}),
        },
    }
    if detail:
        event["detail"] = detail
    TELEMETRY_LOG.append(event)

    channel = task.telemetry_channel
    if not channel:
        return
    targets = [url for url in [CONTEXT_URL, CONTEXT_GRAPH_URL, RENDERER_URL] if url]
    if not targets:
        return
    async with httpx.AsyncClient(timeout=3.0) as client:
        tasks = []
        for t in targets:
            path = "/telemetry/actuation" if t == CONTEXT_GRAPH_URL else "/telemetry"
            tasks.append(client.post(f"{t}{path}", json=event))
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            logger.debug("VDI telemetry publishing failed", exc_info=True)


async def _call_vdi(path: str, payload: dict) -> dict:
    headers = {}
    if VDI_AGENT_TOKEN:
        headers["Authorization"] = f"Bearer {VDI_AGENT_TOKEN}"
    attempts = max(1, int(os.getenv("VDI_RETRY_ATTEMPTS", "3")))
    backoff_base = float(os.getenv("VDI_RETRY_BACKOFF_BASE_SECONDS", "0.25"))
    backoff_max = float(os.getenv("VDI_RETRY_MAX_DELAY_SECONDS", "2.0"))
    timeout = float(os.getenv("VDI_REQUEST_TIMEOUT_SECONDS", "40.0"))

    last_detail: object = "unknown_error"
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(f"{VDI_AGENT_URL}{path}", json=payload, headers=headers)
            except httpx.RequestError as exc:
                last_detail = str(exc)
                if attempt >= attempts:
                    raise HTTPException(status_code=502, detail={"error": "vdi_unavailable", "detail": last_detail})
                delay = min(backoff_max, backoff_base * (2 ** (attempt - 1)))
                await asyncio.sleep(delay)
                continue

            if resp.status_code in {429} or resp.status_code >= 500:
                try:
                    last_detail = resp.json()
                except Exception:
                    last_detail = resp.text
                if attempt >= attempts:
                    raise HTTPException(status_code=resp.status_code, detail=last_detail)
                delay = min(backoff_max, backoff_base * (2 ** (attempt - 1)))
                await asyncio.sleep(delay)
                continue

            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise HTTPException(status_code=resp.status_code, detail=detail)

            return resp.json()

    raise HTTPException(status_code=502, detail={"error": "vdi_unavailable", "detail": last_detail})


@app.post("/vdi/tasks/browse")
async def vdi_browse(task: VdiBrowseRequest, _: None = Depends(verify_auth)) -> dict:
    await _policy_gate("vdi.browse", task.risk_level, task.person_id)
    action_id = task.action_id or f"vdi_{uuid.uuid4().hex}"
    await publish_vdi_telemetry(
        action_id=action_id,
        intent="vdi.browse",
        status="pending",
        lifecycle="started",
        task=task,
    )
    done = asyncio.Event()
    interval = float(os.getenv("VDI_PROGRESS_INTERVAL_SECONDS", "0"))

    async def _heartbeat() -> None:
        if interval <= 0:
            return
        start = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(interval)
            if done.is_set():
                break
            await publish_vdi_telemetry(
                action_id=action_id,
                intent="vdi.browse",
                status="pending",
                lifecycle="in_progress",
                task=task,
                telemetry={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )

    hb_task = asyncio.create_task(_heartbeat())
    try:
        payload = task.model_dump(exclude={"telemetry_channel", "action_id", "trace_id"}, exclude_none=True)
        result = await _call_vdi("/tasks/browse", payload)
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.browse",
            status="ok",
            lifecycle="completed",
            task=task,
        )
        return result
    except HTTPException as exc:
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.browse",
            status="error",
            lifecycle="failed",
            task=task,
            detail=str(exc.detail),
        )
        raise
    finally:
        done.set()
        hb_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb_task


@app.post("/vdi/tasks/form-submit")
async def vdi_form_submit(task: VdiFormSubmitRequest, _: None = Depends(verify_auth)) -> dict:
    await _policy_gate("vdi.form_submit", task.risk_level, task.person_id)
    action_id = task.action_id or f"vdi_{uuid.uuid4().hex}"
    await publish_vdi_telemetry(
        action_id=action_id,
        intent="vdi.form_submit",
        status="pending",
        lifecycle="started",
        task=task,
    )
    done = asyncio.Event()
    interval = float(os.getenv("VDI_PROGRESS_INTERVAL_SECONDS", "0"))

    async def _heartbeat() -> None:
        if interval <= 0:
            return
        start = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(interval)
            if done.is_set():
                break
            await publish_vdi_telemetry(
                action_id=action_id,
                intent="vdi.form_submit",
                status="pending",
                lifecycle="in_progress",
                task=task,
                telemetry={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )

    hb_task = asyncio.create_task(_heartbeat())
    try:
        payload = task.model_dump(exclude={"telemetry_channel", "action_id", "trace_id"}, exclude_none=True)
        result = await _call_vdi("/tasks/form-submit", payload)
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.form_submit",
            status="ok",
            lifecycle="completed",
            task=task,
        )
        return result
    except HTTPException as exc:
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.form_submit",
            status="error",
            lifecycle="failed",
            task=task,
            detail=str(exc.detail),
        )
        raise
    finally:
        done.set()
        hb_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb_task


@app.post("/vdi/tasks/download")
async def vdi_download(task: VdiDownloadRequest, _: None = Depends(verify_auth)) -> dict:
    await _policy_gate("vdi.download", task.risk_level, task.person_id)
    action_id = task.action_id or f"vdi_{uuid.uuid4().hex}"
    await publish_vdi_telemetry(
        action_id=action_id,
        intent="vdi.download",
        status="pending",
        lifecycle="started",
        task=task,
    )
    done = asyncio.Event()
    interval = float(os.getenv("VDI_PROGRESS_INTERVAL_SECONDS", "0"))

    async def _heartbeat() -> None:
        if interval <= 0:
            return
        start = time.monotonic()
        while not done.is_set():
            await asyncio.sleep(interval)
            if done.is_set():
                break
            await publish_vdi_telemetry(
                action_id=action_id,
                intent="vdi.download",
                status="pending",
                lifecycle="in_progress",
                task=task,
                telemetry={"elapsed_ms": int((time.monotonic() - start) * 1000)},
            )

    hb_task = asyncio.create_task(_heartbeat())
    try:
        payload = task.model_dump(exclude={"telemetry_channel", "action_id", "trace_id"}, exclude_none=True)
        result = await _call_vdi("/tasks/download", payload)
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.download",
            status="ok",
            lifecycle="completed",
            task=task,
        )
        return result
    except HTTPException as exc:
        await publish_vdi_telemetry(
            action_id=action_id,
            intent="vdi.download",
            status="error",
            lifecycle="failed",
            task=task,
            detail=str(exc.detail),
        )
        raise
    finally:
        done.set()
        hb_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb_task


if __name__ == "__main__":
    uvicorn.run("unison_actuation.app:app", host=ACTUATION_HOST, port=ACTUATION_PORT, reload=False)

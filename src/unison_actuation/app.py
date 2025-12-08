from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional, Deque, List

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from collections import deque

from unison_actuation.drivers.base import DriverError, DriverRegistry
from unison_actuation.drivers.desktop_driver import DesktopAutomationDriver
from unison_actuation.drivers.logging_driver import LoggingDriver
from unison_actuation.drivers.mock_home_driver import MockHomeDriver
from unison_actuation.drivers.mock_robot_driver import MockRobotDriver
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

# In-memory telemetry buffer for dev/test visibility
TELEMETRY_LOG: Deque[dict] = deque(maxlen=100)

driver_registry = DriverRegistry(
    [
        LoggingDriver(),
        DesktopAutomationDriver(),
        MockHomeDriver(),
        MockRobotDriver(),
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
async def actuate(envelope: ActionEnvelope, decision: ActionDecision = Depends(get_decision)) -> JSONResponse | ActionResult:
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
    if decision.rewritten_intent:
        envelope.intent = decision.rewritten_intent

    result = await driver.execute(envelope)
    await publish_telemetry(envelope, result, envelope.telemetry_channel)
    return result


@app.get("/telemetry/recent")
async def telemetry_recent(limit: int = 20) -> List[dict]:
    """Return recent telemetry events (best-effort dev visibility)."""
    return list(TELEMETRY_LOG)[-limit:]


if __name__ == "__main__":
    uvicorn.run("unison_actuation.app:app", host=ACTUATION_HOST, port=ACTUATION_PORT, reload=False)

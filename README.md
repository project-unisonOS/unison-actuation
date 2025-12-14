# unison-actuation

Safety-first actuation service for UnisonOS. Transforms high-level intents from `unison-orchestrator` into deterministic, policy-validated actions for physical and high-impact digital actuators. Provides envelope validation, policy/consent enforcement, driver routing, telemetry, and audit logging.

## Status
New core service (proposed) — integrates with orchestrator/policy/consent/identity/context; ships logging-only and mock drivers for devstack.

## Features (initial scope)
- Accepts structured **Action Envelopes** from orchestrator and validates identity, scopes, and policy.
- Risk classification with constraint checks and optional confirmation handshakes.
- Pluggable driver adapters for OS automation, smart home, robotics, and avatars; logging-only fallback.
- Telemetry pipeline to `unison-context` / `unison-context-graph` and `unison-experience-renderer`.
- Dual sync/async execution; durable audit and rejection logs.

## Layout
- `src/unison_actuation/app.py` — FastAPI app, routing, lifecycle hooks.
- `src/unison_actuation/schemas.py` — Action Envelope models/validators.
- `src/unison_actuation/drivers/` — base driver + logging, desktop stub, mock home, mock robot.
- Optional driver stubs: MQTT adapter (`device.publish` on `device_class=mqtt`, medium risk cap).
- `schemas/` — JSON Schema + TS typings for Action Envelope.
- `docs/architecture.md` — service architecture and integration contract.
- `docker/` — container entrypoint and compose hints.
- `tests/` — unit tests for envelope validation and driver routing.
- Endpoints: `POST /actuate` (Action Envelope), `GET /telemetry/recent`, `GET /health`, `GET /readyz`.
- VDI proxy endpoints: `POST /vdi/tasks/browse`, `/vdi/tasks/form-submit`, `/vdi/tasks/download` (forwarded to `unison-agent-vdi` with policy gating).

## Run locally
```bash
cd unison-actuation
python3 -m venv .venv && . .venv/bin/activate
pip install -c ../constraints.txt -r requirements.txt
UVICORN_RELOAD=true python -m unison_actuation.app
```

## Environment
- `ACTUATION_PORT` / `ACTUATION_HOST` — service bind.
- `ORCHESTRATOR_URL`, `POLICY_URL`, `CONSENT_URL`, `IDENTITY_URL`, `CONTEXT_URL`, `CONTEXT_GRAPH_URL`, `RENDERER_URL` — downstream integrations.
- `ACTUATION_LOGGING_ONLY=true` — bypass drivers and log-only mode.
- `ACTUATION_ALLOWED_RISK_LEVELS=low,medium` — gate high-risk actions unless explicitly enabled.
- `ACTUATION_REQUIRE_AUTH=true` and `ACTUATION_SERVICE_TOKEN` — require Bearer token on `/actuate`.
- `ACTUATION_REQUIRED_SCOPES=actuation.*` — optional comma list; enforced against `policy_context.scopes`.
- `VDI_AGENT_URL` / `VDI_AGENT_TOKEN` — upstream VDI task service (`unison-agent-vdi`) and optional token.
- `VDI_PROGRESS_INTERVAL_SECONDS` — emit periodic in-progress telemetry while waiting (0 disables).
- `VDI_RETRY_ATTEMPTS`, `VDI_RETRY_BACKOFF_BASE_SECONDS`, `VDI_RETRY_MAX_DELAY_SECONDS` — bounded retry/backoff on `429/5xx` and network errors.
- `VDI_REQUEST_TIMEOUT_SECONDS` — per-attempt timeout for upstream VDI calls.

## Tests
```bash
cd unison-actuation
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OTEL_SDK_DISABLED=true python -m pytest
```

## Next
- Wire into `unison-devstack/docker-compose.yml`.
- Register Action Envelope contract in `unison-docs/dev/specs`.
- Add orchestrator “proposed_action” tool output and envelope builder.
- Remaining roadmap:
  - Renderer UX for actuation telemetry/confirmations.
  - Enforce consent when no actuation grant exists (especially high-risk).
  - Expand policy defaults for device classes/capabilities.
  - Add real drivers (ROS2/desktop automation) with sandboxing and capability maps.
  - Switch auth to JWT verification via unison-auth with scope checks.
  - Add devstack smoke/CI coverage for actuation telemetry/confirmation.
  - Move to tagged releases and update devstack to consume tags.

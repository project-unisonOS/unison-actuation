# Unison Actuation Architecture

## Purpose
Unison Actuation is the deterministic control plane for any physical or high-impact digital actuator. It accepts **Action Envelopes** from `unison-orchestrator`, validates identity/consent/policy, classifies risk, routes to the correct driver, and emits telemetry back into `unison-context`, `unison-context-graph`, and the renderer.

## Request / Response Flow
1. **Proposal** — `unison-orchestrator` emits a `proposed_action` envelope (schema in `schemas/action-envelope.schema.json`) to `POST /actuate`.
2. **Envelope validation** — `unison-actuation` performs JSON Schema + Pydantic validation and checks `ACTUATION_ALLOWED_RISK_LEVELS`.
3. **Identity & consent** — tokens are validated via `unison-identity` (future), and existing grants are fetched from `unison-consent` when `policy_context.consent_reference` is absent.
4. **Policy** — envelope is normalized and posted to `unison-policy /evaluate`. Decisions may reject, rewrite intent/parameters, or request confirmation.
5. **Confirmation (optional)** — renderer/context surface a confirmation ask; `POST /actions/{id}/confirm` (future) unblocks execution.
6. **Driver routing** — the driver registry selects a driver by `intent.name` + `target.device_class`. `ACTUATION_LOGGING_ONLY=true` forces `LoggingDriver`.
7. **Execution** — driver executes deterministically (idempotent where possible) and produces an `ActionResult`.
8. **Telemetry** — lifecycle events are sent to `unison-context`, `unison-context-graph`, and optionally `unison-experience-renderer` via the `telemetry_channel`.
9. **Audit** — all decisions (permit/reject/confirm) and executions are logged to `unison-policy /audit` (future hook) and internal logs.

## Safety Boundaries
- **Ingress**: Only accepts structured envelopes; no free-form LLM actions. JWTs and scopes validated by `unison-identity`.
- **Policy & consent**: Hard gate via `unison-policy` + `unison-consent`. `ACTUATION_ALLOWED_RISK_LEVELS` blocks high-risk by default.
- **Driver sandbox**: Drivers are isolated modules. High-impact drivers should run in restricted containers with explicit capabilities.
- **Logging-only mode**: `ACTUATION_LOGGING_ONLY=true` ensures dry runs in development.

## Driver Plugin System
- **Base class**: `drivers/base.py` defines `BaseDriver`, `Capability`, and `DriverRegistry`.
- **Routing**: registry chooses driver by intent + device_class; fallbacks raise deterministic errors.
- **Capabilities**: drivers declare capabilities (`turn_on`, `robot.move`, `desktop.command`, etc.) with optional device class filters.
- **Error model**: `DriverError` for deterministic execution failures; surfaced as `400 Bad Request`.
- **Initial drivers**: `LoggingDriver`, `DesktopAutomationDriver` (stub for computer-use/MCP), `MockHomeDriver`, `MockRobotDriver`.
- **Telemetry**: drivers return `ActionResult.telemetry`; the service forwards to context/renderer.

## Telemetry Pipeline
- Publishes best-effort lifecycle events (`submitted`, `permitted`, `executing`, `completed/failed`) to:
  - `unison-context` (for person/session timeline),
  - `unison-context-graph` (for graph state),
  - `unison-experience-renderer` (for live UX updates).
- `telemetry_channel.topic` allows routing to specific graph streams or renderer channels.

## Logging Strategy
- Structured JSON logs with `action_id`, `person_id`, `risk_level`, and driver name.
- Policy decisions, rewrites, and rejections are logged with reasons.
- Logging-only mode records attempted actions without executing drivers.

## Integration Contracts
- **Orchestrator**: emits `proposed_action` tool output; posts Action Envelopes to `/actuate`; streams telemetry back to renderer/context graph; handles async updates.
- **Policy / Consent / Identity**: extend scopes `actuation.*`, `actuation.home.*`, `actuation.robot.*`, `actuation.desktop.*`; use `/evaluate`, `/consent`, and `/audit`.
- **Context / Context-Graph**: receive telemetry for lifecycle and device health; surface confirmations and state deltas.
- **Renderer**: displays confirmations, progress, and outcomes; may request repeats/aborts.

## Deployment
- Dockerized FastAPI service (`docker/Dockerfile`) with env-configured downstream URLs.
- Runs independently in devstack with mock drivers; production drivers mounted via plugin packages.

## Migration Notes
- Start with logging-only in devstack.
- Gradually enable mock home/robot drivers and enforce policy scopes.
- Introduce confirmation flows for `risk_level=high` before enabling real hardware adapters.

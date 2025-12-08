from __future__ import annotations

import dataclasses
import enum
import uuid
from datetime import datetime, time, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ActionProvenance(BaseModel):
    source_intent: str = Field(..., description="Original semantic intent or tool name")
    orchestrator_task_id: Optional[str] = Field(
        None, description="Orchestrator task identifier that proposed this action"
    )
    model_version: Optional[str] = Field(
        None, description="Model or planner version that generated the proposal"
    )
    generated_at: Optional[datetime] = Field(
        None, description="Timestamp when the proposal was produced"
    )

    model_config = {"protected_namespaces": ()}


class ActionTarget(BaseModel):
    device_id: str = Field(..., description="Unique device identifier")
    device_class: str = Field(..., description="Category such as light, robot, browser")
    location: Optional[str] = Field(None, description="Location hint for policy decisions")
    endpoint: Optional[str] = Field(
        None, description="Driver-specific endpoint/topic/service identifier"
    )


class ActionIntent(BaseModel):
    name: str = Field(..., description="Canonical intent name, e.g. turn_on, move_to")
    parameters: Dict[str, object] = Field(
        default_factory=dict, description="Structured parameters for the driver"
    )
    human_readable: Optional[str] = Field(
        None, description="Human readable paraphrase for audit and consent prompts"
    )


class ActionConstraints(BaseModel):
    max_duration_ms: Optional[int] = Field(
        None, ge=1, description="Hard stop for long-running actions"
    )
    required_confirmations: int = Field(
        0, ge=0, description="Number of confirmations required before execution"
    )
    quiet_hours: Optional[List[str]] = Field(
        None, description="List of quiet hour windows in HH:MM-HH:MM format"
    )
    allowed_risk_levels: Optional[List[RiskLevel]] = Field(
        None, description="Optional override of acceptable risk levels for this action"
    )

    @field_validator("quiet_hours")
    @classmethod
    def validate_quiet_hours(cls, windows: Optional[List[str]]) -> Optional[List[str]]:
        if not windows:
            return windows
        for window in windows:
            if "-" not in window:
                raise ValueError(f"Invalid quiet hours window '{window}'")
            start, end = window.split("-", 1)
            cls._parse_time(start)
            cls._parse_time(end)
        return windows

    @staticmethod
    def _parse_time(value: str) -> time:
        hours, minutes = value.split(":", 1)
        return time(hour=int(hours), minute=int(minutes))


class PolicyContext(BaseModel):
    scopes: List[str] = Field(default_factory=list, description="Requested policy scopes")
    consent_reference: Optional[str] = Field(
        None, description="Consent grant or transaction identifier"
    )
    justification: Optional[str] = Field(None, description="Why the action is needed")
    risk_level: RiskLevel = Field(RiskLevel.low, description="Proposed risk level")


class TelemetryChannel(BaseModel):
    topic: str = Field(..., description="Channel identifier or topic name")
    delivery: str = Field("stream", description="Delivery mode: stream or batch")
    include_parameters: bool = Field(True, description="Whether to include parameters in telemetry")


class ActionEnvelope(BaseModel):
    schema_version: str = Field("1.0", description="Action Envelope schema version")
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    person_id: str
    target: ActionTarget
    intent: ActionIntent
    risk_level: RiskLevel = Field(RiskLevel.low)
    constraints: ActionConstraints = Field(default_factory=ActionConstraints)
    policy_context: PolicyContext = Field(default_factory=PolicyContext)
    telemetry_channel: Optional[TelemetryChannel] = Field(
        None, description="Where to publish action lifecycle telemetry"
    )
    provenance: Optional[ActionProvenance] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = Field(
        None, description="Correlation identifier for orchestrator/session tracing"
    )

    @model_validator(mode="after")
    def validate_risk(self) -> "ActionEnvelope":
        allowed = self.constraints.allowed_risk_levels
        if allowed and self.risk_level not in allowed:
            raise ValueError(f"Risk level {self.risk_level} not permitted by constraints")
        return self


class ActionDecision(BaseModel):
    permitted: bool
    status: str
    reason: Optional[str] = None
    risk_level: RiskLevel = Field(RiskLevel.low)
    requires_confirmation: bool = False
    rewritten_intent: Optional[ActionIntent] = None


class ActionResult(BaseModel):
    action_id: str
    status: str
    message: Optional[str] = None
    telemetry: Dict[str, object] = Field(default_factory=dict)
    driver: Optional[str] = None


# Lightweight dataclasses for non-pydantic consumers (e.g., CLI tooling/tests).
@dataclasses.dataclass
class ActionEnvelopeData:
    schema_version: str
    action_id: str
    person_id: str
    target: ActionTarget
    intent: ActionIntent
    risk_level: RiskLevel
    constraints: ActionConstraints
    policy_context: PolicyContext
    telemetry_channel: Optional[TelemetryChannel] = None
    provenance: Optional[ActionProvenance] = None
    created_at: Optional[datetime] = None
    correlation_id: Optional[str] = None

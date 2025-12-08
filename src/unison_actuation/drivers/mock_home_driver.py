import logging
from typing import Iterable

from unison_actuation.drivers.base import BaseDriver, Capability, DriverError
from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class MockHomeDriver(BaseDriver):
    """Simulated smart home driver (MQTT/REST hubs in real deployments)."""

    def name(self) -> str:
        return "mock-home"

    def capabilities(self) -> Iterable[Capability]:
        return [
            Capability("turn_on", device_classes=["light", "switch"]),
            Capability("turn_off", device_classes=["light", "switch"]),
            Capability("set_brightness", device_classes=["light"]),
        ]

    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        intent = envelope.intent.name
        if intent not in {"turn_on", "turn_off", "set_brightness"}:
            raise DriverError(f"Unsupported home intent {intent}")

        logger.info(
            "MockHomeDriver %s device_id=%s params=%s",
            intent,
            envelope.target.device_id,
            envelope.intent.parameters,
        )
        return ActionResult(
            action_id=envelope.action_id,
            status="completed",
            message=f"Mock home action {intent} applied",
            driver=self.name(),
            telemetry={"device_id": envelope.target.device_id, "intent": intent},
        )

import logging
import os
from typing import Iterable

from unison_actuation.drivers.base import BaseDriver, Capability, DriverError
from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class MqttDriver(BaseDriver):
    """MQTT adapter stub for smart home hubs or devices.

    Uses environment variables for broker configuration; execution is best-effort and
    safe for devstack (no persistent connection maintained).
    """

    def __init__(self):
        self.broker = os.getenv("ACTUATION_MQTT_BROKER", "mqtt://localhost:1883")

    def name(self) -> str:
        return "mqtt"

    def capabilities(self) -> Iterable[Capability]:
        return [
            Capability("device.publish", device_classes=["mqtt"]),
        ]

    def max_risk_level(self) -> str:
        return "medium"

    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        topic = envelope.intent.parameters.get("topic")
        payload = envelope.intent.parameters.get("payload")
        if not topic:
            raise DriverError("MQTT topic required")
        # Lazy import to avoid hard dependency when unused.
        try:
            import asyncio_mqtt  # type: ignore
        except Exception:
            logger.warning("asyncio_mqtt not installed; logging-only mode for MQTT")
            return ActionResult(
                action_id=envelope.action_id,
                status="logged",
                message="MQTT client not installed; action logged only",
                driver=self.name(),
                telemetry={"topic": topic, "broker": self.broker},
            )
        try:
            async with asyncio_mqtt.Client(self.broker) as client:  # type: ignore
                await client.publish(topic, str(payload))
        except Exception as exc:
            raise DriverError(f"MQTT publish failed: {exc}") from exc

        return ActionResult(
            action_id=envelope.action_id,
            status="completed",
            message="MQTT publish sent",
            driver=self.name(),
            telemetry={"topic": topic, "broker": self.broker},
        )

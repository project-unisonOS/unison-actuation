import logging
from typing import Iterable

from unison_actuation.drivers.base import BaseDriver, Capability, DriverError
from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class MockRobotDriver(BaseDriver):
    """Simulated robotics driver (ROS2/OPC UA/CAN/etc.)."""

    def name(self) -> str:
        return "mock-robot"

    def capabilities(self) -> Iterable[Capability]:
        return [
            Capability("robot.move", device_classes=["robot"]),
            Capability("robot.dock", device_classes=["robot"]),
            Capability("robot.stop", device_classes=["robot"]),
        ]

    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        intent = envelope.intent.name
        if intent not in {"robot.move", "robot.dock", "robot.stop"}:
            raise DriverError(f"Unsupported robot intent {intent}")

        logger.info(
            "MockRobotDriver %s device_id=%s params=%s",
            intent,
            envelope.target.device_id,
            envelope.intent.parameters,
        )
        status = "completed" if intent != "robot.stop" else "halted"
        return ActionResult(
            action_id=envelope.action_id,
            status=status,
            message=f"Mock robot intent {intent} executed",
            driver=self.name(),
            telemetry={"intent": intent, "pose": envelope.intent.parameters},
        )

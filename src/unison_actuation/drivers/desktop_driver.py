import logging
from typing import Iterable

from unison_actuation.drivers.base import BaseDriver, Capability, DriverError
from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class DesktopAutomationDriver(BaseDriver):
    """Stub desktop/system automation driver.

    Intended to wrap computer-use/MCP flows; here it logs and returns deterministic responses.
    """

    def name(self) -> str:
        return "desktop-automation"

    def capabilities(self) -> Iterable[Capability]:
        return [
            Capability("desktop.command", device_classes=["desktop", "browser"]),
            Capability("desktop.navigate", device_classes=["desktop", "browser"]),
        ]

    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        intent = envelope.intent.name
        if intent not in {"desktop.command", "desktop.navigate"}:
            raise DriverError(f"Unsupported desktop intent {intent}")

        logger.info(
            "DesktopAutomationDriver executing %s on %s params=%s",
            intent,
            envelope.target.device_id,
            envelope.intent.parameters,
        )
        # Deterministic stub response; real implementation would delegate to MCP/agent
        return ActionResult(
            action_id=envelope.action_id,
            status="accepted",
            message="Desktop automation stub executed",
            driver=self.name(),
            telemetry={"parameters": envelope.intent.parameters},
        )

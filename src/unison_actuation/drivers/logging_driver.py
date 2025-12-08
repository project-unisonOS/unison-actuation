import logging
from typing import Iterable

from unison_actuation.drivers.base import BaseDriver, Capability
from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class LoggingDriver(BaseDriver):
    """Development driver that records actions without performing them."""

    def __init__(self, accept_all: bool = True):
        self.accept_all = accept_all

    def name(self) -> str:
        return "logging"

    def capabilities(self) -> Iterable[Capability]:
        if self.accept_all:
            # Wildcard: declare a generic capability name
            return [Capability(name="*")]
        return []

    def can_handle(self, envelope: ActionEnvelope) -> bool:
        return self.accept_all or super().can_handle(envelope)

    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        logger.info(
            "Logging-only execution for action_id=%s intent=%s device_class=%s target=%s",
            envelope.action_id,
            envelope.intent.name,
            envelope.target.device_class,
            envelope.target.device_id,
        )
        return ActionResult(
            action_id=envelope.action_id,
            status="logged",
            message="Action recorded only (logging mode)",
            driver=self.name(),
            telemetry={"logged": True},
        )

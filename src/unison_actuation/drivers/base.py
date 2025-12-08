from __future__ import annotations

import abc
import logging
from typing import Iterable, List, Sequence

from unison_actuation.schemas import ActionEnvelope, ActionResult

logger = logging.getLogger(__name__)


class DriverError(Exception):
    """Raised when a driver fails to execute an action."""


class Capability:
    """Represents a capability string and optional device classes it applies to."""

    def __init__(self, name: str, device_classes: Sequence[str] | None = None):
        self.name = name
        self.device_classes = set(device_classes or [])

    def matches(self, envelope: ActionEnvelope) -> bool:
        if self.device_classes and envelope.target.device_class not in self.device_classes:
            return False
        return envelope.intent.name == self.name


class BaseDriver(abc.ABC):
    """Base class for all actuation drivers."""

    @abc.abstractmethod
    def name(self) -> str:
        ...

    @abc.abstractmethod
    def capabilities(self) -> Iterable[Capability]:
        ...

    def max_risk_level(self) -> str:
        """Override to cap allowable risk levels for this driver ('low'|'medium'|'high')."""
        return "high"

    def can_handle(self, envelope: ActionEnvelope) -> bool:
        return any(cap.matches(envelope) for cap in self.capabilities())

    @abc.abstractmethod
    async def execute(self, envelope: ActionEnvelope) -> ActionResult:
        """Execute an action. Implementations must be deterministic and idempotent where possible."""


class DriverRegistry:
    def __init__(self, drivers: Sequence[BaseDriver]):
        self._drivers = list(drivers)

    def route(self, envelope: ActionEnvelope) -> BaseDriver:
        for driver in self._drivers:
            if driver.can_handle(envelope):
                return driver
        raise DriverError(
            f"No driver registered for intent '{envelope.intent.name}' and device_class "
            f"'{envelope.target.device_class}'"
        )

    @property
    def drivers(self) -> List[BaseDriver]:
        return self._drivers

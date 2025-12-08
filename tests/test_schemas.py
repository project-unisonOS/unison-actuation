import pytest
from pydantic import ValidationError

from unison_actuation.schemas import ActionEnvelope, ActionIntent, ActionTarget, RiskLevel
from unison_actuation.drivers.base import DriverRegistry
from unison_actuation.drivers.mock_home_driver import MockHomeDriver


def test_quiet_hours_validation():
    envelope = ActionEnvelope(
        person_id="person-1",
        target=ActionTarget(device_id="light-1", device_class="light"),
        intent=ActionIntent(name="turn_on", parameters={}),
        constraints={"quiet_hours": ["22:00-06:00"]},
    )
    assert envelope.constraints.quiet_hours == ["22:00-06:00"]


def test_invalid_risk_level_rejected():
    with pytest.raises(ValidationError):
        ActionEnvelope(
            person_id="person-1",
            target=ActionTarget(device_id="light-1", device_class="light"),
            intent=ActionIntent(name="turn_on", parameters={}),
            risk_level=RiskLevel.high,
            constraints={"allowed_risk_levels": [RiskLevel.low]},
        )


def test_driver_routing_selects_mock_home():
    registry = DriverRegistry([MockHomeDriver()])
    envelope = ActionEnvelope(
        person_id="person-1",
        target=ActionTarget(device_id="light-1", device_class="light"),
        intent=ActionIntent(name="turn_on", parameters={}),
    )
    driver = registry.route(envelope)
    assert driver.name() == "mock-home"

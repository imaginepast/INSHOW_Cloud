"""Temperature and operating status sensors for INSHOW controllers."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import InShowConfigEntry
from .entity import InShowEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InShowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        entity
        for cid in coordinator.devices
        for entity in (
            InShowCurrentTemperature(coordinator, cid),
            InShowTargetTemperature(coordinator, cid),
            InShowOperatingStatus(coordinator, cid),
        )
    )


class InShowCurrentTemperature(InShowEntity, SensorEntity):
    _attr_translation_key = "indoor_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, controller_id: str) -> None:
        super().__init__(coordinator, controller_id)
        self._attr_unique_id = f"{controller_id}_current_temperature"

    @property
    def native_value(self) -> float | None:
        return self.device_state.get("current_temp")


class InShowTargetTemperature(InShowEntity, SensorEntity):
    """Read-only target temperature, available even while away mode is active."""

    _attr_translation_key = "target_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, controller_id: str) -> None:
        super().__init__(coordinator, controller_id)
        self._attr_unique_id = f"{controller_id}_target_temperature"

    @property
    def native_value(self) -> float | None:
        return self.device_state.get("target_temp")


class InShowOperatingStatus(InShowEntity, SensorEntity):
    """Human-readable operating status: away, idle, or actively heating."""

    _attr_translation_key = "operating_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["away", "idle", "heating"]

    def __init__(self, coordinator, controller_id: str) -> None:
        super().__init__(coordinator, controller_id)
        self._attr_unique_id = f"{controller_id}_operating_status"

    @property
    def native_value(self) -> str | None:
        away_mode = self.device_state.get("away_mode")
        if away_mode is True:
            return "away"

        relay_on = self.device_state.get("relay_on")
        if relay_on is True:
            return "heating"
        if relay_on is False:
            return "idle"
        return None

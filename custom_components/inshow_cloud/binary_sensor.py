"""Heating relay binary sensor for INSHOW controllers."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    async_add_entities(InShowHeatingRelay(coordinator, cid) for cid in coordinator.devices)


class InShowHeatingRelay(InShowEntity, BinarySensorEntity):
    _attr_translation_key = "heating_relay"
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator, controller_id: str) -> None:
        super().__init__(coordinator, controller_id)
        self._attr_unique_id = f"{controller_id}_heating_relay"

    @property
    def is_on(self) -> bool | None:
        return self.device_state.get("relay_on")

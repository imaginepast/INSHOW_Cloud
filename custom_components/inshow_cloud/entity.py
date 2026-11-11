"""Base entity for INSHOW controllers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import InShowCoordinator


class InShowEntity(CoordinatorEntity[InShowCoordinator]):
    """One entity belonging to one INSHOW controller."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: InShowCoordinator, controller_id: str) -> None:
        super().__init__(coordinator)
        self.controller_id = controller_id
        info = coordinator.devices[controller_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller_id)},
            name=info["room"],
            manufacturer="INSHOW",
            model="75DF / T01",
        )

    @property
    def device_state(self) -> dict[str, Any]:
        return self.coordinator.devices[self.controller_id]

    @property
    def available(self) -> bool:
        # State is pushed over MQTT, so "available" means "MQTT is connected".
        return self.coordinator.mqtt_connected

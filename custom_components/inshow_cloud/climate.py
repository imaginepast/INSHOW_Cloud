"""Climate entity for INSHOW controllers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_TEMP, MIN_TEMP, TEMP_STEP
from .coordinator import InShowConfigEntry
from .entity import InShowEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: InShowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(InShowClimate(coordinator, cid) for cid in coordinator.devices)


class InShowClimate(InShowEntity, ClimateEntity):
    """Heating thermostat.

    The controller is always powered and has no real "off": pressing its power
    button switches it to away mode. Home Assistant therefore shows away mode as
    HVAC mode ``off`` and normal heating as ``heat``.
    """

    _attr_name = None  # the entity is the device's main feature
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP

    def __init__(self, coordinator, controller_id: str) -> None:
        super().__init__(coordinator, controller_id)
        self._attr_unique_id = f"{controller_id}_climate"

    @property
    def _away(self) -> bool:
        return self.device_state.get("away_mode") is True

    @property
    def supported_features(self) -> ClimateEntityFeature:
        # The controller does not accept a new target temperature while away.
        if self._away:
            return ClimateEntityFeature(0)
        return ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._away else HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self._away:
            return HVACAction.OFF
        return HVACAction.HEATING if self.device_state.get("relay_on") else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return self.device_state.get("current_temp")

    @property
    def target_temperature(self) -> float | None:
        return self.device_state.get("target_temp")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        if self._away:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="away_mode_locked"
            )
        await self.coordinator.async_set_target_temperature(
            self.controller_id, float(temperature)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode not in (HVACMode.HEAT, HVACMode.OFF):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="hvac_mode_unsupported"
            )
        if hvac_mode == self.hvac_mode:
            return  # already in that mode: nothing to send
        await self.coordinator.async_set_away_mode(
            self.controller_id, hvac_mode == HVACMode.OFF
        )

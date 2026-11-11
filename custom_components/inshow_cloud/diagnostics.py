"""Diagnostics with personal data removed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import InShowConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "unique_id",
    "title",
    "room",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: InShowConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "mqtt_connected": coordinator.mqtt_connected,
        "device_count": len(coordinator.devices),
        "devices": [async_redact_data(d, TO_REDACT) for d in coordinator.devices.values()],
    }

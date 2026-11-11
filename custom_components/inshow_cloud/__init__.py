"""INSHOW Cloud integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import InShowApi, InShowApiError, InShowAuthError
from .const import DOMAIN, MAX_SIGN_IN_REJECTIONS, PLATFORMS
from .coordinator import InShowConfigEntry, InShowCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: InShowConfigEntry) -> bool:
    api = InShowApi(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    # Consecutive sign-in rejections per config entry (kept across Home Assistant's setup retries).
    rejections: dict[str, int] = hass.data.setdefault(DOMAIN, {})
    try:
        zones = await api.async_login_and_get_zones()
    except InShowAuthError as err:
        attempt = rejections.get(entry.entry_id, 0) + 1
        _LOGGER.warning(
            "INSHOW sign-in was rejected (%s), attempt %d of %d",
            err.code,
            attempt,
            MAX_SIGN_IN_REJECTIONS,
        )
        if attempt >= MAX_SIGN_IN_REJECTIONS:
            rejections.pop(entry.entry_id, None)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        rejections[entry.entry_id] = attempt
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="sign_in_retry",
            translation_placeholders={
                "attempt": str(attempt),
                "max": str(MAX_SIGN_IN_REJECTIONS),
            },
        ) from err
    except InShowApiError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_connect"
        ) from err
    rejections.pop(entry.entry_id, None)

    coordinator = InShowCoordinator(hass, entry, zones)
    if not coordinator.devices:
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="no_devices")

    entry.runtime_data = coordinator
    # Also runs if a later setup step fails, so the MQTT thread never leaks.
    entry.async_on_unload(coordinator.async_stop)

    await coordinator.async_start_mqtt()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InShowConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

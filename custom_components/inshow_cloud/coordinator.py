"""MQTT-push coordinator for INSHOW controllers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
import secrets
import ssl
from typing import Any

import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    COMMAND_CONFIRM_TIMEOUT,
    DOMAIN,
    MQTT_CONNECT_TIMEOUT,
    MQTT_HOST,
    MQTT_KEEPALIVE,
    MQTT_ORIGIN,
    MQTT_PORT,
    MQTT_WS_PATH,
)
from .protocol import (
    apply_command,
    build_aliases,
    command_topic,
    mask_topic,
    parse_message,
    parse_payload,
    parse_zones,
    safe_repr,
)

_LOGGER = logging.getLogger(__name__)

# CONNACK return codes (MQTT 3.1.1) that mean "you are not allowed", i.e. retrying
# will not help: 4 = bad user name or password, 5 = not authorized.
_CONNACK_REFUSED = {4, 5}

type InShowConfigEntry = ConfigEntry[InShowCoordinator]

_PENDING_LABELS = {"target_temp": "target temperature", "away_mode": "away mode"}


class InShowCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Holds controller state, fed by MQTT messages (no polling)."""

    config_entry: InShowConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: InShowConfigEntry, zones: list[dict[str, Any]]
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None
        )
        self.devices, self.topics = parse_zones(zones)
        self.data = self.devices
        self._aliases = build_aliases(self.devices)  # placeholders for IDs in debug logs
        self.mqtt_client: mqtt.Client | None = None
        self.mqtt_connected = False
        self._stopped = False
        self._connected_event = asyncio.Event()
        self._connect_error: Any = None
        # (controller_id, state key) -> (last confirmed value, cancel rollback timer)
        self._pending: dict[tuple[str, str], tuple[Any, Callable[[], None]]] = {}

    # ------------------------------------------------------------------ MQTT

    async def async_start_mqtt(self) -> None:
        """Connect to the broker and wait for the first CONNACK."""
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"inshow_mobile_{secrets.token_hex(4)}",
            clean_session=True,
            protocol=mqtt.MQTTv311,
            transport="websockets",
        )
        client.ws_set_options(path=MQTT_WS_PATH, headers={"Origin": MQTT_ORIGIN})
        # Loading CA certificates blocks, so build the context in the executor.
        client.tls_set_context(
            await self.hass.async_add_executor_job(ssl.create_default_context)
        )
        client.reconnect_delay_set(min_delay=1, max_delay=60)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        try:
            await self.hass.async_add_executor_job(
                client.connect, MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE
            )
        except (OSError, ValueError) as err:
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="mqtt_connect_failed",
                translation_placeholders={"error": type(err).__name__},
            ) from err

        self.mqtt_client = client
        client.loop_start()

        try:
            async with asyncio.timeout(MQTT_CONNECT_TIMEOUT):
                await self._connected_event.wait()
        except TimeoutError as err:
            await self.async_stop()
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="mqtt_connect_failed",
                translation_placeholders={"error": "timeout"},
            ) from err

        if self._connect_error is not None:
            code = getattr(self._connect_error, "value", None)
            description = str(self._connect_error)
            await self.async_stop()
            if code in _CONNACK_REFUSED:
                raise ConfigEntryError(
                    translation_domain=DOMAIN,
                    translation_key="mqtt_refused",
                    translation_placeholders={"error": description},
                )
            raise ConfigEntryNotReady(
                translation_domain=DOMAIN,
                translation_key="mqtt_connect_failed",
                translation_placeholders={"error": description},
            )

    async def async_stop(self) -> None:
        """Disconnect and release resources. Safe to call more than once."""
        self._stopped = True
        for _, cancel in self._pending.values():
            cancel()
        self._pending.clear()
        self.mqtt_connected = False
        client, self.mqtt_client = self.mqtt_client, None
        if client is not None:
            await self.hass.async_add_executor_job(self._shutdown_client, client)

    @staticmethod
    def _shutdown_client(client: mqtt.Client) -> None:
        client.disconnect()
        client.loop_stop()

    def _schedule(self, func: Callable[..., None], *args: Any) -> None:
        """Run ``func`` on the event loop from the paho network thread."""
        if self._stopped:
            return
        try:
            self.hass.loop.call_soon_threadsafe(func, *args)
        except RuntimeError:  # loop closed during shutdown
            pass

    # ---- paho callbacks (run in paho's thread: do not touch HA state here) --

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if getattr(reason_code, "is_failure", False):
            self._schedule(self._handle_connect_refused, reason_code)
            return
        for topic in sorted(self.topics):
            client.subscribe(topic, qos=0)
        self._schedule(self._handle_connected)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        self._schedule(self._handle_disconnected, reason_code)

    def _on_message(self, client, userdata, message) -> None:
        payload = message.payload.decode("utf-8", errors="replace").strip()
        self._schedule(self._handle_message, message.topic, payload)

    # ---- handlers (run on the event loop) -----------------------------------

    def _handle_connected(self) -> None:
        if self._connected_event.is_set() and not self.mqtt_connected:
            _LOGGER.info("INSHOW MQTT connection restored")
        else:
            _LOGGER.info("INSHOW MQTT connected (%d controller(s))", len(self.devices))
        self.mqtt_connected = True
        self._connect_error = None
        self._connected_event.set()
        self.async_set_updated_data(self.devices)

    def _handle_connect_refused(self, reason_code: Any) -> None:
        if not self._connected_event.is_set():
            self._connect_error = reason_code
            self._connected_event.set()
            return
        _LOGGER.warning("INSHOW MQTT reconnect refused: %s", reason_code)
        self.mqtt_connected = False
        self.async_set_updated_data(self.devices)

    def _handle_disconnected(self, reason_code: Any) -> None:
        if self.mqtt_connected:
            _LOGGER.warning("INSHOW MQTT connection lost (%s); reconnecting", reason_code)
        self.mqtt_connected = False
        self.async_set_updated_data(self.devices)

    def _handle_message(self, topic: str, payload: str) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "INSHOW rx topic=%s payload=%s",
                mask_topic(topic, self._aliases),
                safe_repr(parse_payload(payload)),
            )
        parsed = parse_message(topic, payload)
        if parsed is None:
            return
        controller_id, command, data = parsed
        state = self.devices.get(controller_id)
        if state is None:
            return

        touched = apply_command(state, command, data)

        for key in touched:
            self._confirm_pending(controller_id, key)
        if touched:
            _LOGGER.debug("INSHOW update: %s", sorted(touched))
            self.async_set_updated_data(self.devices)

    # ---------------------------------------------------------------- commands

    def _publish_command(self, controller_id: str, command: str, payload: str) -> None:
        """Publish ``cmnd/inshow/<id>/<command>``; raises if it cannot be sent."""
        client = self.mqtt_client
        if client is None or not self.mqtt_connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            )
        _LOGGER.debug(
            "INSHOW tx topic=%s payload=%s",
            mask_topic(command_topic(controller_id, command), self._aliases),
            safe_repr(payload),
        )
        result = client.publish(command_topic(controller_id, command), payload, qos=0)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"rc": str(result.rc)},
            )

    async def async_set_target_temperature(self, controller_id: str, value: float) -> None:
        """Publish a new target temperature."""
        self._publish_command(controller_id, "TEMPTARGETSET", f"{value:g}")
        self._set_pending(controller_id, "target_temp", value)

    async def async_set_away_mode(self, controller_id: str, enabled: bool) -> None:
        """Enable or disable away mode (command payload: 1 = away, 0 = home)."""
        self._publish_command(controller_id, "AWAYMODESET", "1" if enabled else "0")
        self._set_pending(controller_id, "away_mode", enabled)

    @callback
    def _set_pending(self, controller_id: str, key: str, value: Any) -> None:
        """Show ``value`` right away, but roll back if the controller never confirms."""
        state = self.devices[controller_id]
        slot = (controller_id, key)
        previous = state.get(key)
        if slot in self._pending:
            # Keep the last *confirmed* value as the rollback target.
            previous, cancel = self._pending.pop(slot)
            cancel()

        @callback
        def _expired(_now: datetime) -> None:
            entry = self._pending.pop(slot, None)
            if entry is None:
                return
            state[key] = entry[0]
            if entry[0] != value:
                _LOGGER.warning(
                    "INSHOW controller did not confirm the new %s; reverting",
                    _PENDING_LABELS.get(key, key),
                )
            self.async_set_updated_data(self.devices)

        cancel = async_call_later(self.hass, COMMAND_CONFIRM_TIMEOUT, _expired)
        self._pending[slot] = (previous, cancel)
        state[key] = value
        self.async_set_updated_data(self.devices)

    @callback
    def _confirm_pending(self, controller_id: str, key: str) -> None:
        entry = self._pending.pop((controller_id, key), None)
        if entry is not None:
            entry[1]()

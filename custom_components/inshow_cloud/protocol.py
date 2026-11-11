"""Pure protocol helpers for the INSHOW cloud (no Home Assistant imports)."""

from __future__ import annotations

import json
import re
from typing import Any

DEVICE_TYPE_THERMOSTAT = 2

_TRUE = {"1", "true", "on", "yes"}
_FALSE = {"0", "false", "off", "no", ""}


def float_or_none(value: Any) -> float | None:
    """Convert a value to float, returning None when that is not possible."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def bool_or_none(value: Any) -> bool | None:
    """Convert 0/1/"ON"/"off"/True... to bool, None when unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def away_from_onoff(value: Any) -> bool | None:
    """Away mode from the server's ``onoff`` field.

    The controller has no real "off": the server reports ``onoff == 0`` while the
    controller is in away mode, so away is the inverse of ``onoff``.
    """
    onoff = bool_or_none(value)
    return None if onoff is None else not onoff


def parse_payload(payload: str) -> Any:
    """Decode a JSON payload, falling back to the raw string."""
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return payload


_SAFE_WORDS = {
    "on", "off", "true", "false", "yes", "no", "none", "null",
    "heat", "cool", "auto", "away", "home", "idle", "heating",
}
_SAFE_NUMBER = re.compile(r"^[0-9.:+-]{1,6}$")  # "1", "21.5", "12:30" - not phone numbers
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,19}$")
_HEX_ID = re.compile(r"^[0-9a-fA-F]{16,}$")
# Keys whose value identifies something (_id, id, deviceId, user_id, uid, serialNo...)
_ID_KEY = re.compile(r"^_?id$|_id$|[a-z]Id$|^uid$|^[Ss]erial")


def safe_repr(value: Any, depth: int = 0) -> str:
    """Debug-log representation that cannot leak identifiers or personal data.

    Numbers, booleans, short numeric strings and a small fixed vocabulary (``ON``,
    ``heat``...) are shown. Every other string (user names, IDs, serials, e-mail
    addresses, tokens...) is replaced by ``<str:LEN>``, and unusual or long
    dictionary keys by ``<key>``.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return repr(value)
    if isinstance(value, str):
        if value.lower() in _SAFE_WORDS or _SAFE_NUMBER.match(value):
            return repr(value)
        return f"<str:{len(value)}>"
    if depth >= 3:
        return "<...>"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda kv: str(kv[0]))[:30]
        body = ", ".join(_safe_item(k, v, depth) for k, v in items)
        return "{" + body + "}"
    if isinstance(value, (list, tuple)):
        shown = ", ".join(safe_repr(v, depth + 1) for v in value[:5])
        extra = f", ...+{len(value) - 5}" if len(value) > 5 else ""
        return f"[{shown}{extra}]"
    return f"<{type(value).__name__}>"


def _safe_item(key: Any, value: Any, depth: int) -> str:
    name = key if isinstance(key, str) and _SAFE_KEY.match(key) else "<key>"
    if _ID_KEY.search(name) and isinstance(value, (int, str)) and not isinstance(value, bool):
        return f"{name}: <id>"
    return f"{name}: {safe_repr(value, depth + 1)}"


def build_aliases(devices: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Map real controller IDs to stable placeholders (<ctrl1>, <ctrl2>...)."""
    return {cid: f"<ctrl{i}>" for i, cid in enumerate(sorted(devices), 1)}


def mask_topic(topic: str, aliases: dict[str, str]) -> str:
    """Replace IDs inside a topic; any unknown long hex segment is hidden too."""
    return "/".join(
        aliases.get(seg) or ("<id>" if _HEX_ID.match(seg) else seg) for seg in topic.split("/")
    )


def command_topic(controller_id: str, command: str) -> str:
    return f"cmnd/inshow/{controller_id}/{command}"


def _iter_thermostats(zones: list[dict[str, Any]]):
    """Yield (controller_id, group_name, device) for every real thermostat."""
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        for group in zone.get("groups") or []:
            if not isinstance(group, dict):
                continue
            group_name = group.get("name") or "INSHOW"
            for device in group.get("devices") or []:
                if not isinstance(device, dict):
                    continue
                if device.get("type") != DEVICE_TYPE_THERMOSTAT or device.get("isVirtual"):
                    continue
                controller_id = str(device.get("controllerId") or "")
                if controller_id:
                    yield controller_id, group_name, device


def parse_zones(zones: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Extract thermostat devices and MQTT topics from the /zones response."""
    devices: dict[str, dict[str, Any]] = {}
    topics: set[str] = set()

    for controller_id, group_name, device in _iter_thermostats(zones):
        item = device.get("item") or {}
        if not isinstance(item, dict):
            item = {}
        away = away_from_onoff(item.get("onoff"))
        devices[controller_id] = {
            "room": group_name,
            "current_temp": float_or_none(item.get("currentTemp")),
            # While a controller is away the server's targetTemp is not necessarily the
            # setpoint the controller restores when away mode ends, so it is unknown.
            "target_temp": None if away else float_or_none(item.get("targetTemp")),
            "relay_on": bool_or_none(item.get("relayOn")),
            "away_mode": away,
        }
        topics.add(f"stat/inshow/{controller_id}/#")

    return devices, topics


def parse_message(topic: str, payload: str) -> tuple[str, str, Any] | None:
    """Split ``stat/inshow/<controller>/<COMMAND>`` into (controller_id, command, data).

    Returns None for any other topic.
    """
    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == "stat" and parts[1] == "inshow":
        return parts[2], parts[3], parse_payload(payload)
    return None


def apply_command(state: dict[str, Any], command: str, data: Any) -> set[str]:
    """Apply a ``stat/inshow/<id>/<COMMAND>`` message. Returns the keys touched."""
    touched: set[str] = set()
    if not isinstance(data, dict):
        return touched

    if command == "TEMPTARGETSET":
        value = float_or_none(data.get("TempTargetSet"))
        if value is not None:
            state["target_temp"] = value
            touched.add("target_temp")
    elif command == "ROOMTEMPREAL":
        value = float_or_none(data.get("Temperature"))
        if value is not None:
            state["current_temp"] = value
            touched.add("current_temp")
        relay = bool_or_none(data.get("POWER_RL"))
        if relay is not None:
            state["relay_on"] = relay
            touched.add("relay_on")
    elif command == "AWAYMODESET":
        # 1 = away, 0 = home: the same convention as the command itself.
        away = bool_or_none(data.get("AwayModeSet"))
        if away is not None:
            state["away_mode"] = away
            touched.add("away_mode")
    return touched

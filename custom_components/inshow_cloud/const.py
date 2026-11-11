"""Constants for the INSHOW Cloud integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "inshow_cloud"
PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR]

API_BASE = "https://iot.interiorshow.kr/api"

MQTT_HOST = "iot.interiorshow.kr"
MQTT_PORT = 443
MQTT_WS_PATH = "/ws"
MQTT_ORIGIN = "https://iot.interiorshow.kr"
MQTT_KEEPALIVE = 60
MQTT_CONNECT_TIMEOUT = 15  # seconds to wait for the first CONNACK

# How long to wait for the controller to confirm a command (target temperature,
# away mode) before the optimistic value is rolled back.
COMMAND_CONFIRM_TIMEOUT = 10

# A rejected sign-in is retried this many times in a row before the user is asked for the
# password again: the same credentials were seen to work minutes after being rejected.
MAX_SIGN_IN_REJECTIONS = 3

MIN_TEMP = 9.0
MAX_TEMP = 35.0
TEMP_STEP = 0.5

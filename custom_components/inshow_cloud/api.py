"""Minimal INSHOW cloud REST client (login + zone discovery)."""

from __future__ import annotations

import re
from typing import Any

import aiohttp

from .const import API_BASE

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
SUCCESS_CODE = "0000"


class InShowApiError(Exception):
    """Base error: the cloud could not be reached or answered unexpectedly."""


class InShowAuthError(InShowApiError):
    """The server rejected the sign-in.

    ``code`` is the server's short reason (``"HTTP 401"`` or its ``resultCode``) so it can be
    logged. It is never the server's free-text message, which may contain account details.
    """

    def __init__(self, message: str, code: str = "?") -> None:
        super().__init__(message)
        self.code = code


_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,12}$")


def _safe_code(value: Any) -> str:
    """A server result code that is safe to log, or "?"."""
    text = str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    return text if _CODE.match(text) else "?"


class InShowApi:
    """Talks to the INSHOW REST API using a shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self._session.request(
                method, f"{API_BASE}{path}", timeout=REQUEST_TIMEOUT, **kwargs
            ) as response:
                response.raise_for_status()
                result = await response.json(content_type=None)
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                raise InShowAuthError(f"HTTP {err.status}", code=f"HTTP {err.status}") from err
            raise InShowApiError(f"HTTP {err.status}") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise InShowApiError("cannot reach INSHOW cloud") from err
        except ValueError as err:  # invalid JSON
            raise InShowApiError("invalid JSON response") from err

        if not isinstance(result, dict):
            raise InShowApiError("unexpected response format")
        return result

    async def async_login(self) -> str:
        """Sign in and return the access token."""
        result = await self._request(
            "POST",
            "/authorize/signIn",
            json={"type": "e", "email": self._email, "password": self._password},
        )
        if result.get("resultCode") != SUCCESS_CODE:
            # Only the short code is kept: the message can contain account details.
            raise InShowAuthError("sign-in rejected", code=_safe_code(result.get("resultCode")))
        data = result.get("resultData")
        token = data.get("accessToken") if isinstance(data, dict) else None
        if not token:
            raise InShowApiError("sign-in response has no access token")
        return str(token)

    async def async_get_zones(self, token: str) -> list[dict[str, Any]]:
        """Return the account's zones (with groups and devices)."""
        result = await self._request(
            "GET",
            "/zones",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if result.get("resultCode") != SUCCESS_CODE:
            raise InShowApiError("device list request rejected")
        zones = result.get("resultData") or []
        if not isinstance(zones, list):
            raise InShowApiError("unexpected device list format")
        return zones

    async def async_login_and_get_zones(self) -> list[dict[str, Any]]:
        token = await self.async_login()
        return await self.async_get_zones(token)

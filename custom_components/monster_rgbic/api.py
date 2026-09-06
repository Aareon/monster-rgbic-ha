"""Async client for Monster Smart Lighting RGBIC bulbs (Ayla cloud via Copilot SSO)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    AYLA_ADS_BASE,
    AYLA_APP_ID,
    AYLA_APP_SECRET,
    AYLA_USER_BASE,
    COPILOT_APPLICATION_ID,
    COPILOT_BASE,
    COPILOT_PARTNER_ID,
    SPHERE_BASE,
)

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=25)


class MonsterAuthError(Exception):
    """Raised when authentication fails (bad credentials, etc.)."""


class MonsterApiError(Exception):
    """Raised on a non-auth API failure."""


class MonsterAylaApi:
    """Reproduces the Monster app's Copilot -> partner ticket -> Ayla SSO chain."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._ayla_token: str | None = None
        self._ayla_expiry: float = 0.0
        # A stable per-install device id for the Copilot login payload.
        self._device_id = str(uuid.uuid4())

    # ---- auth chain ---------------------------------------------------

    async def _copilot_login(self) -> str:
        body = {
            "authenticationDetails": {
                "applicationId": COPILOT_APPLICATION_ID,
                "email": self._email,
                "password": self._password,
            },
            # The Copilot API validates these enums and returns 400 otherwise.
            # It advertises deviceType TABLET/PHONE/PC/Unknown and osType
            # IOS/ANDROID/BROWSER/Unknown, but empirically only these values are
            # accepted (e.g. osType "Unknown" is rejected despite being listed).
            "deviceDetails": {
                "applicationVersion": "1.0.0",
                "deviceId": self._device_id,
                "deviceModel": "HomeAssistant",
                "deviceType": "phone",
                "osType": "android",
                "osVersion": "1",
                "timezone": {
                    "currentTimeMillis": 0,
                    "offsetMillis": 0,
                    "timezoneId": "UTC",
                },
            },
        }
        async with self._session.post(
            f"{COPILOT_BASE}/v4/auth/login", json=body, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status in (400, 401, 403):
                raise MonsterAuthError(f"Copilot login rejected ({resp.status})")
            if resp.status >= 300:
                raise MonsterApiError(f"Copilot login failed ({resp.status})")
            data = await resp.json()
        token = data.get("accessToken") or data.get("access_token")
        if not token:
            raise MonsterAuthError("Copilot login returned no accessToken")
        return token

    async def _get_partner_ticket(self, copilot_token: str) -> str:
        url = f"{SPHERE_BASE}/v2/partner/{COPILOT_PARTNER_ID}/acquire_ticket"
        async with self._session.post(
            url,
            headers={"Authorization": f"Bearer {copilot_token}"},
            json={"applicationId": COPILOT_APPLICATION_ID},
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status >= 300:
                raise MonsterApiError(f"acquire_ticket failed ({resp.status})")
            data = await resp.json()
        ticket = data.get("partnerTicket")
        if not ticket:
            raise MonsterApiError("acquire_ticket returned no partnerTicket")
        return ticket

    async def _ayla_token_sign_in(self, ticket: str) -> None:
        async with self._session.post(
            f"{AYLA_USER_BASE}/api/v1/token_sign_in",
            json={
                "token": ticket,
                "app_id": AYLA_APP_ID,
                "app_secret": AYLA_APP_SECRET,
            },
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status >= 300:
                raise MonsterApiError(f"Ayla token_sign_in failed ({resp.status})")
            data = await resp.json()
        self._ayla_token = data["access_token"]
        # Refresh 5 min before the stated expiry (default 24h).
        self._ayla_expiry = time.monotonic() + int(data.get("expires_in", 86400)) - 300

    async def async_authenticate(self) -> None:
        """Run the full login -> ticket -> Ayla session chain."""
        copilot_token = await self._copilot_login()
        ticket = await self._get_partner_ticket(copilot_token)
        await self._ayla_token_sign_in(ticket)
        _LOGGER.debug("Monster/Ayla authentication succeeded")

    async def _ensure_token(self) -> None:
        if self._ayla_token is None or time.monotonic() >= self._ayla_expiry:
            await self.async_authenticate()

    # ---- device API ---------------------------------------------------

    async def _ayla_request(
        self, method: str, path: str, *, json: Any | None = None, _retry: bool = True
    ) -> Any:
        await self._ensure_token()
        headers = {"Authorization": f"auth_token {self._ayla_token}"}
        async with self._session.request(
            method,
            f"{AYLA_ADS_BASE}{path}",
            headers=headers,
            json=json,
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            if resp.status == 401 and _retry:
                # Token went stale early; re-auth once and retry.
                self._ayla_token = None
                return await self._ayla_request(
                    method, path, json=json, _retry=False
                )
            if resp.status >= 300:
                raise MonsterApiError(f"{method} {path} failed ({resp.status})")
            if resp.status == 204 or resp.content_length == 0:
                return None
            return await resp.json()

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Return the list of device dicts (each has a 'device' object)."""
        data = await self._ayla_request("GET", "/apiv1/devices.json")
        return [d["device"] for d in data if "device" in d]

    async def async_get_properties(self, dsn: str) -> dict[str, Any]:
        """Return {property_name: value} for a device."""
        data = await self._ayla_request(
            "GET", f"/apiv1/dsns/{dsn}/properties.json"
        )
        out: dict[str, Any] = {}
        for item in data:
            prop = item.get("property", {})
            name = prop.get("name")
            if name is not None:
                out[name] = prop.get("value")
        return out

    async def async_set_property(self, dsn: str, name: str, value: Any) -> None:
        """Create a datapoint (write a property value)."""
        await self._ayla_request(
            "POST",
            f"/apiv1/dsns/{dsn}/properties/{name}/datapoints.json",
            json={"datapoint": {"value": value}},
        )

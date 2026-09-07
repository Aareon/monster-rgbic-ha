"""DataUpdateCoordinator for Monster RGBIC devices."""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MonsterApiError, MonsterAuthError, MonsterAylaApi
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MonsterCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Polls all Monster RGBIC devices and exposes {dsn: {prop: value}}."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: MonsterAylaApi
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.entry = entry
        # dsn -> device info dict (product_name, oem_model, etc.)
        self.devices: dict[str, dict[str, Any]] = {}
        # dsn -> MonsterLanController (populated by __init__.py when local mode is on)
        self.lan_controllers: dict[str, Any] = {}
        # Optimistic write overlay: dsn -> {prop: (value, expiry_monotonic)}.
        # LAN writes carry echo:"none", so the cloud can report a stale value for
        # a while after a change. We apply the commanded value locally right away
        # and keep it on top of poll results until the cloud agrees or it expires.
        self._optimistic: dict[str, dict[str, tuple[Any, float]]] = {}

    # How long an optimistic value overrides a disagreeing cloud poll.
    OPTIMISTIC_TTL = 120.0

    def set_optimistic(self, dsn: str, name: str, value: Any) -> None:
        """Record a just-written value and reflect it immediately in state."""
        self._optimistic.setdefault(dsn, {})[name] = (
            value,
            time.monotonic() + self.OPTIMISTIC_TTL,
        )
        if self.data and dsn in self.data:
            self.data[dsn][name] = value
            self.async_update_listeners()

    def _apply_optimistic(self, dsn: str, props: dict[str, Any]) -> dict[str, Any]:
        """Overlay unexpired optimistic values; drop ones the cloud has caught
        up to or that have expired."""
        pending = self._optimistic.get(dsn)
        if not pending:
            return props
        now = time.monotonic()
        for name, (value, expiry) in list(pending.items()):
            if now >= expiry or props.get(name) == value:
                del pending[name]  # expired, or cloud now agrees
            else:
                props[name] = value  # still pending: keep our value
        if not pending:
            self._optimistic.pop(dsn, None)
        return props

    async def _async_setup(self) -> None:
        """One-time discovery of devices (HA calls this before first refresh)."""
        try:
            devices = await self.api.async_get_devices()
        except MonsterAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MonsterApiError as err:
            raise UpdateFailed(f"Could not list devices: {err}") from err
        self.devices = {d["dsn"]: d for d in devices if d.get("dsn")}

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        if not self.devices:
            await self._async_setup()
        result: dict[str, dict[str, Any]] = {}
        for dsn in self.devices:
            try:
                props = await self.api.async_get_properties(dsn)
            except MonsterApiError as err:
                raise UpdateFailed(f"Poll failed for {dsn}: {err}") from err
            result[dsn] = self._apply_optimistic(dsn, props)
        return result

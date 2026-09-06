"""DataUpdateCoordinator for Monster RGBIC devices."""

from __future__ import annotations

import logging
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
                result[dsn] = await self.api.async_get_properties(dsn)
            except MonsterApiError as err:
                raise UpdateFailed(f"Poll failed for {dsn}: {err}") from err
        return result

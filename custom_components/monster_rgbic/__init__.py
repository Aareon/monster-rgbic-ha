"""The Monster Smart Lighting (RGBIC) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MonsterAylaApi
from .const import CONF_EMAIL, CONF_LOCAL, CONF_PASSWORD
from .coordinator import MonsterCoordinator
from .lan import BASE_PORT, MonsterLanController

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]

type MonsterConfigEntry = ConfigEntry[MonsterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MonsterConfigEntry) -> bool:
    """Set up Monster RGBIC from a config entry."""
    session = async_get_clientsession(hass)
    api = MonsterAylaApi(session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = MonsterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    # Optionally bring up LAN-mode controllers (best-effort; falls back to cloud).
    coordinator.lan_controllers = {}
    if entry.data.get(CONF_LOCAL, True):
        for index, (dsn, dev) in enumerate(coordinator.devices.items()):
            # Each bulb gets its own local port (it connects back to us).
            controller = MonsterLanController(
                api, dsn, dev.get("lan_ip"), BASE_PORT + index
            )
            try:
                if await controller.async_start():
                    coordinator.lan_controllers[dsn] = controller
                    _LOGGER.info("LAN control active for %s", dsn)
                else:
                    await controller.async_stop()
                    _LOGGER.info("LAN control unavailable for %s; using cloud", dsn)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("LAN setup failed for %s; using cloud", dsn)
                await controller.async_stop()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MonsterConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for controller in entry.runtime_data.lan_controllers.values():
            await controller.async_stop()
    return unloaded

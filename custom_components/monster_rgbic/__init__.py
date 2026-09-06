"""The Monster Smart Lighting (RGBIC) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MonsterAylaApi
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN
from .coordinator import MonsterCoordinator

PLATFORMS: list[Platform] = [Platform.LIGHT]

type MonsterConfigEntry = ConfigEntry[MonsterCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MonsterConfigEntry) -> bool:
    """Set up Monster RGBIC from a config entry."""
    session = async_get_clientsession(hass)
    api = MonsterAylaApi(
        session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = MonsterCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MonsterConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

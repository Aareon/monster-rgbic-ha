"""Light platform for Monster Smart Lighting (RGBIC)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MonsterConfigEntry
from .const import (
    DOMAIN,
    MODE_COLOR,
    PROP_BRIGHTNESS,
    PROP_COLOR_SELECT,
    PROP_MODE,
    PROP_POWER,
)
from .coordinator import MonsterCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MonsterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Monster RGBIC lights from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        MonsterLight(coordinator, dsn) for dsn in coordinator.devices
    )


class MonsterLight(CoordinatorEntity[MonsterCoordinator], LightEntity):
    """A Monster RGBIC light strip."""

    _attr_has_entity_name = True
    _attr_name = None  # entity takes the device's name
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_color_mode = ColorMode.RGB

    def __init__(self, coordinator: MonsterCoordinator, dsn: str) -> None:
        super().__init__(coordinator)
        self._dsn = dsn
        info = coordinator.devices.get(dsn, {})
        self._attr_unique_id = dsn
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsn)},
            name=info.get("product_name") or "Monster RGBIC",
            manufacturer="Monster",
            model=info.get("oem_model") or "rgbic",
        )

    @property
    def _props(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._dsn) or {}

    @property
    def available(self) -> bool:
        return super().available and self._dsn in (self.coordinator.data or {})

    @property
    def is_on(self) -> bool | None:
        val = self._props.get(PROP_POWER)
        return None if val is None else bool(val)

    @property
    def brightness(self) -> int | None:
        val = self._props.get(PROP_BRIGHTNESS)
        if val is None:
            return None
        return round(int(val) / 100 * 255)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        val = self._props.get(PROP_COLOR_SELECT)
        if val is None:
            return None
        packed = int(val)
        return ((packed >> 16) & 0xFF, (packed >> 8) & 0xFF, packed & 0xFF)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally setting brightness and/or RGB color."""
        api = self.coordinator.api

        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            # Switch to solid-color mode, then set the packed color.
            await api.async_set_property(self._dsn, PROP_MODE, MODE_COLOR)
            await api.async_set_property(
                self._dsn, PROP_COLOR_SELECT, (r << 16) | (g << 8) | b
            )

        if ATTR_BRIGHTNESS in kwargs:
            pct = max(1, round(kwargs[ATTR_BRIGHTNESS] / 255 * 100))
            await api.async_set_property(self._dsn, PROP_BRIGHTNESS, pct)

        await api.async_set_property(self._dsn, PROP_POWER, 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.coordinator.api.async_set_property(self._dsn, PROP_POWER, 0)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

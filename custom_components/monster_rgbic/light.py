"""Light platform for Monster Smart Lighting (RGBIC)."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MonsterConfigEntry
from .const import (
    DOMAIN,
    EFFECT_FAMILIES,
    EFFECT_MAX_SLOTS,
    MODE_COLOR,
    PROP_BRIGHTNESS,
    PROP_COLOR_BRIGHT,
    PROP_COLOR_SAT,
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
    _attr_supported_features = LightEntityFeature.EFFECT

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
        # In color mode the visible dimmer is color_bright, not brightness.
        val = self._props.get(PROP_COLOR_BRIGHT)
        if val is None:
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

    def _effect_map(self) -> dict[str, tuple[str, str, int]]:
        """Build ``label -> (mode, selector_property, slot_index)`` from the
        device's own scene slots, so DIY renames and per-device banks are
        reflected. Empty/unpopulated slots are skipped.
        """
        props = self._props
        out: dict[str, tuple[str, str, int]] = {}
        for mode, (prefix, pat_prop, family) in EFFECT_FAMILIES.items():
            for idx in range(EFFECT_MAX_SLOTS):
                slot = props.get(f"{prefix}{idx:02d}")
                if not slot or not isinstance(slot, str):
                    continue
                try:
                    name = json.loads(slot).get("n")
                except (ValueError, TypeError):
                    name = None
                if not name:
                    continue
                out[f"{family}: {name}"] = (mode, pat_prop, idx)
        return out

    @property
    def effect_list(self) -> list[str] | None:
        effects = list(self._effect_map())
        return effects or None

    @property
    def effect(self) -> str | None:
        """The currently active built-in scene, if the bulb is in a scene mode."""
        mode = self._props.get(PROP_MODE)
        family = EFFECT_FAMILIES.get(mode)
        if family is None:
            return None  # color / white mode -> no effect
        _prefix, pat_prop, _label = family
        idx = self._props.get(pat_prop)
        if idx is None:
            return None
        target = (mode, pat_prop, int(idx))
        for label, mapping in self._effect_map().items():
            if mapping == target:
                return label
        return None

    # Property base types (LAN needs these; the cloud call ignores them).
    _BASE_TYPES = {
        PROP_POWER: "boolean",
        PROP_MODE: "string",
        PROP_BRIGHTNESS: "integer",
        PROP_COLOR_SELECT: "integer",
        PROP_COLOR_BRIGHT: "integer",
        PROP_COLOR_SAT: "integer",
        "st_pat": "integer",
        "dyn_pat": "integer",
        "mus_pat": "integer",
        "diy_pat": "integer",
        "per_ic_pat": "integer",
    }

    async def _set(self, name: str, value: Any) -> None:
        """Write one property: try LAN first, fall back to the cloud.

        On success we record the value optimistically, because a LAN write
        (echo:"none") isn't immediately reflected by the cloud we poll.
        """
        controller = self.coordinator.lan_controllers.get(self._dsn)
        if controller is not None and controller.available:
            base_type = self._BASE_TYPES.get(name, "integer")
            if await controller.async_set_property(name, value, base_type):
                self.coordinator.set_optimistic(self._dsn, name, value)
                return
        await self.coordinator.api.async_set_property(self._dsn, name, value)
        self.coordinator.set_optimistic(self._dsn, name, value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on, optionally setting an effect, RGB color, and/or brightness."""
        if ATTR_EFFECT in kwargs:
            mapping = self._effect_map().get(kwargs[ATTR_EFFECT])
            if mapping is not None:
                mode, pat_prop, idx = mapping
                # Switch to the scene family, then select the slot.
                await self._set(PROP_MODE, mode)
                await self._set(pat_prop, idx)
        elif ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            # Switch to solid-color mode, then set the packed color.
            await self._set(PROP_MODE, MODE_COLOR)
            await self._set(PROP_COLOR_SELECT, (r << 16) | (g << 8) | b)

        if ATTR_BRIGHTNESS in kwargs:
            pct = max(1, round(kwargs[ATTR_BRIGHTNESS] / 255 * 100))
            # color_bright is the visible dimmer in color mode.
            await self._set(PROP_COLOR_BRIGHT, pct)

        await self._set(PROP_POWER, 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._set(PROP_POWER, 0)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

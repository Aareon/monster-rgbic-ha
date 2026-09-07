"""Config flow for Monster Smart Lighting (RGBIC)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import ble
from .api import MonsterApiError, MonsterAuthError, MonsterAylaApi
from .const import CONF_EMAIL, CONF_LOCAL, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Onboarding form field keys (not persisted).
CONF_DEVICE = "device"
CONF_SSID = "ssid"
CONF_WIFI_PASSWORD = "wifi_password"
CONF_SECURITY = "security"

STEP_ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        # LAN control is fast and offline-capable, but the Monster app can't be
        # connected at the same time (the bulb allows one local controller).
        vol.Optional(CONF_LOCAL, default=True): bool,
    }
)


class MonsterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Monster RGBIC config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose: sign in, or onboard a new strip over Bluetooth."""
        return self.async_show_menu(
            step_id="user", menu_options=["account", "onboard"]
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in with the Monster app account (cloud + LAN control)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = MonsterAylaApi(session, email, user_input[CONF_PASSWORD])
            try:
                await api.async_authenticate()
            except MonsterAuthError:
                errors["base"] = "invalid_auth"
            except MonsterApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error validating Monster login")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=f"Monster Lighting ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_LOCAL: user_input.get(CONF_LOCAL, True),
                    },
                )

        return self.async_show_form(
            step_id="account", data_schema=STEP_ACCOUNT_SCHEMA, errors=errors
        )

    async def async_step_onboard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Provision a new strip onto Wi-Fi over BLE, then claim it to the account.

        Wi-Fi provisioning and the regtoken are fully local; the final device
        claim is the one required Ayla cloud call (it provisions the LAN key).
        """
        errors: dict[str, str] = {}
        strips = ble.discover_strips(self.hass)
        if not strips:
            return self.async_abort(reason="no_strip_found")

        existing = self._async_current_entries()

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            if existing:
                email = existing[0].data[CONF_EMAIL]
                password = existing[0].data[CONF_PASSWORD]
            else:
                email = user_input[CONF_EMAIL].strip()
                password = user_input[CONF_PASSWORD]
            api = MonsterAylaApi(session, email, password)
            try:
                await api.async_authenticate()
                dsn = await ble.async_onboard(
                    self.hass,
                    user_input[CONF_DEVICE],
                    user_input[CONF_SSID],
                    user_input.get(CONF_WIFI_PASSWORD, ""),
                    user_input[CONF_SECURITY],
                )
                found = await ble.async_find_new_strip(self.hass, session)
                if not found:
                    errors["base"] = "regtoken_not_found"
                else:
                    _ip, regtoken = found
                    await api.async_register_device(dsn, regtoken)
            except MonsterAuthError:
                errors["base"] = "invalid_auth"
            except MonsterApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("BLE onboarding failed")
                errors["base"] = "onboard_failed"
            else:
                if existing:
                    # Account already configured: reload it so the newly claimed
                    # device shows up, and finish.
                    self.hass.config_entries.async_schedule_reload(
                        existing[0].entry_id
                    )
                    return self.async_abort(reason="device_added")
                await self.async_set_unique_id(email.lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Monster Lighting ({email})",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_LOCAL: True,
                    },
                )

        device_options = {s.address: f"{s.name} ({s.address})" for s in strips}
        fields: dict[Any, Any] = {
            vol.Required(CONF_DEVICE): vol.In(device_options),
            vol.Required(CONF_SSID): str,
            vol.Optional(CONF_WIFI_PASSWORD, default=""): str,
            vol.Required(CONF_SECURITY, default="wpa2"): vol.In(list(ble.SECURITY)),
        }
        if not existing:
            # Need account credentials to claim the device.
            fields = {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                **fields,
            }
        return self.async_show_form(
            step_id="onboard", data_schema=vol.Schema(fields), errors=errors
        )

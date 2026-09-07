"""Config flow for Monster Smart Lighting (RGBIC)."""

from __future__ import annotations

import asyncio
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

    # BLE onboarding state (per flow instance).
    _onboard_data: dict[str, Any] | None = None
    _onboard_task: asyncio.Task | None = None
    _onboard_error: str | None = None

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

    # ---- Bluetooth onboarding -----------------------------------------
    #
    # The work runs as two sequential background tasks so the dialog can show a
    # live progress spinner + message: (1) BLE Wi-Fi provisioning, then (2) the
    # LAN regtoken fetch + Ayla claim. On failure we return to the form with the
    # error; on success we create or reload the account entry.

    def _async_onboard_form(
        self, need_creds: bool, errors: dict[str, str]
    ) -> ConfigFlowResult:
        strips = ble.discover_strips(self.hass)
        device_options = {s.address: f"{s.name} ({s.address})" for s in strips}
        fields: dict[Any, Any] = {
            vol.Required(CONF_DEVICE): vol.In(device_options),
            vol.Required(CONF_SSID): str,
            vol.Optional(CONF_WIFI_PASSWORD, default=""): str,
            vol.Required(CONF_SECURITY, default="wpa2"): vol.In(list(ble.SECURITY)),
        }
        if need_creds:
            fields = {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                **fields,
            }
        return self.async_show_form(
            step_id="onboard", data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_onboard(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect onboarding inputs and kick off provisioning."""
        errors: dict[str, str] = {}
        if self._onboard_error:
            errors["base"] = self._onboard_error
            self._onboard_error = None

        existing = self._async_current_entries()

        if user_input is not None:
            if existing:
                email = existing[0].data[CONF_EMAIL]
                password = existing[0].data[CONF_PASSWORD]
            else:
                email = user_input[CONF_EMAIL].strip()
                password = user_input[CONF_PASSWORD]
            self._onboard_data = {
                "email": email,
                "password": password,
                "device": user_input[CONF_DEVICE],
                "ssid": user_input[CONF_SSID],
                "wifi_password": user_input.get(CONF_WIFI_PASSWORD, ""),
                "security": user_input[CONF_SECURITY],
                "entry_id": existing[0].entry_id if existing else None,
            }
            self._onboard_task = self.hass.async_create_task(self._async_provision())
            return self.async_show_progress(
                step_id="onboard_ble",
                progress_action="provisioning",
                progress_task=self._onboard_task,
            )

        if not errors and not ble.discover_strips(self.hass):
            return self.async_abort(reason="no_strip_found")
        return self._async_onboard_form(not existing, errors)

    async def _async_provision(self) -> str:
        """Task: authenticate the account, then BLE-provision Wi-Fi. Returns DSN."""
        data = self._onboard_data
        assert data is not None
        session = async_get_clientsession(self.hass)
        api = MonsterAylaApi(session, data["email"], data["password"])
        await api.async_authenticate()
        return await ble.async_onboard(
            self.hass,
            data["device"],
            data["ssid"],
            data["wifi_password"],
            data["security"],
            progress=lambda phase: _LOGGER.debug("onboard phase: %s", phase),
        )

    async def async_step_onboard_ble(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show BLE provisioning progress; then start the claim task."""
        assert self._onboard_task is not None
        if not self._onboard_task.done():
            return self.async_show_progress(
                step_id="onboard_ble",
                progress_action="provisioning",
                progress_task=self._onboard_task,
            )
        try:
            dsn = self._onboard_task.result()
        except MonsterAuthError:
            self._onboard_error = "invalid_auth"
        except MonsterApiError:
            self._onboard_error = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("BLE provisioning failed")
            self._onboard_error = "onboard_failed"
        else:
            self._onboard_data["dsn"] = dsn  # type: ignore[index]
            self._onboard_task = self.hass.async_create_task(self._async_claim())
            return self.async_show_progress(
                step_id="onboard_claim",
                progress_action="claiming",
                progress_task=self._onboard_task,
            )
        return self.async_show_progress_done(next_step_id="onboard")

    async def _async_claim(self) -> None:
        """Task: find the freshly-provisioned strip on the LAN and claim it."""
        data = self._onboard_data
        assert data is not None
        session = async_get_clientsession(self.hass)
        found = None
        for _ in range(48):  # ~4 min: the strip can take minutes to associate
            found = await ble.async_find_new_strip(self.hass, session)
            if found:
                break
            await asyncio.sleep(5)
        if not found:
            self._onboard_error = "regtoken_not_found"
            return
        _ip, regtoken = found
        api = MonsterAylaApi(session, data["email"], data["password"])
        await api.async_register_device(data["dsn"], regtoken)

    async def async_step_onboard_claim(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show claim progress; then finish (or return to the form on error)."""
        assert self._onboard_task is not None
        if not self._onboard_task.done():
            return self.async_show_progress(
                step_id="onboard_claim",
                progress_action="claiming",
                progress_task=self._onboard_task,
            )
        try:
            self._onboard_task.result()
        except MonsterApiError:
            self._onboard_error = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Device claim failed")
            self._onboard_error = self._onboard_error or "onboard_failed"
        if self._onboard_error:
            return self.async_show_progress_done(next_step_id="onboard")
        return self.async_show_progress_done(next_step_id="onboard_finish")

    async def async_step_onboard_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the account entry, or reload the existing one, after a claim."""
        data = self._onboard_data
        assert data is not None
        if data.get("entry_id"):
            self.hass.config_entries.async_schedule_reload(data["entry_id"])
            return self.async_abort(reason="device_added")
        await self.async_set_unique_id(data["email"].lower())
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Monster Lighting ({data['email']})",
            data={
                CONF_EMAIL: data["email"],
                CONF_PASSWORD: data["password"],
                CONF_LOCAL: True,
            },
        )

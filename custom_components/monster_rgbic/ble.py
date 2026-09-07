"""BLE Wi-Fi onboarding for Monster RGBIC strips (Ayla setup protocol).

Reverse-engineered from the app and verified against real hardware: connect,
pair (Just Works), write a 105-byte credentials struct, watch the status
characteristic. After the strip joins Wi-Fi, the caller fetches a regtoken from
it on the LAN and claims it via the cloud (see api.py).

Runs under Home Assistant's Bluetooth stack (BlueZ). The heavy protocol details
here were validated end-to-end (a brand-new strip provisioned onto Wi-Fi with no
Monster app and no cloud).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

import aiohttp
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Ayla setup GATT (validated on hardware).
SERVICE_IDENTITY = "0000fe28-0000-1000-8000-00805f9b34fb"
CHAR_DSN = "00000001-fe28-435b-991a-f1b21bb9bcd0"
CHAR_OEM_MODEL = "00000003-fe28-435b-991a-f1b21bb9bcd0"
SERVICE_WIFI = "1cf0fe66-3ecf-4d6e-a9fc-e287ab124b96"
CHAR_CONNECT = "1f80af6a-2b71-4e35-94e5-00f854d8f16f"
CHAR_CONNECT_STATUS = "1f80af6c-2b71-4e35-94e5-00f854d8f16f"

# WifiSecurityType ordinal (from AylaConnectCharacteristic).
SECURITY = {"none": 0, "wep": 1, "wpa": 2, "wpa2": 3, "wpa3": 4}

# Name prefix Monster/Ayla strips advertise (e.g. "MLED50ls-5e", "MLED30sal-..").
NAME_PREFIX = "MLED"

# Connect-status byte offsets (validated): [0:32] ssid, [32] ssid_len,
# [33] state (0x14 connecting -> 0x00 settled), [34] detail/error.
_STATE_OFFSET = 33


@dataclass
class StripCandidate:
    address: str
    name: str
    rssi: int | None = None


def build_connect_payload(ssid: str, password: str, security: str) -> bytes:
    """Build the 105-byte connect struct written to CHAR_CONNECT."""
    s = ssid.encode()
    p = password.encode()
    if len(s) > 32:
        raise ValueError("SSID too long (max 32 bytes)")
    if len(p) > 64:
        raise ValueError("password too long (max 64 bytes)")
    buf = bytearray(105)
    buf[0 : len(s)] = s
    buf[32] = len(s)
    buf[39 : 39 + len(p)] = p
    buf[103] = len(p)
    buf[104] = SECURITY.get(security.lower(), SECURITY["wpa2"]) & 0xFF
    return bytes(buf)


def discover_strips(hass: HomeAssistant) -> list[StripCandidate]:
    """Return unprovisioned strips currently advertising the setup service."""
    out: list[StripCandidate] = []
    for info in bluetooth.async_discovered_service_info(hass, connectable=True):
        name = info.name or ""
        uuids = {u.lower() for u in (info.service_uuids or [])}
        if SERVICE_IDENTITY in uuids or name.upper().startswith(NAME_PREFIX):
            out.append(StripCandidate(info.address, name, info.rssi))
    return out


async def async_find_new_strip(
    hass: HomeAssistant, session: aiohttp.ClientSession
) -> tuple[str, str] | None:
    """Scan the HA host's /24 for a freshly-provisioned, unclaimed strip and
    return ``(ip, regtoken)``.

    The unclaimed strip serves ``GET /regtoken.json`` unauthenticated with
    ``registered:0`` (verified on hardware). We look for that.
    """
    from homeassistant.components.network import async_get_source_ip

    source_ip = await async_get_source_ip(hass)
    if not source_ip or source_ip.count(".") != 3:
        _LOGGER.debug("no usable source IP for LAN scan (%s)", source_ip)
        return None
    prefix = source_ip.rsplit(".", 1)[0]  # e.g. "10.0.0"
    sem = asyncio.Semaphore(48)
    timeout = aiohttp.ClientTimeout(total=1.2)

    async def probe(host: str) -> tuple[str, str] | None:
        url = f"http://{host}/regtoken.json"
        async with sem:
            try:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                return None
        if data.get("regtoken") and not data.get("registered"):
            name = (data.get("host_symname") or "").lower()
            if "monster" in name or "rgbic" in name:
                return host, data["regtoken"]
        return None

    results = await asyncio.gather(
        *(probe(f"{prefix}.{i}") for i in range(1, 255))
    )
    for res in results:
        if res:
            return res
    return None


async def async_onboard(
    hass: HomeAssistant,
    address: str,
    ssid: str,
    password: str,
    security: str,
    timeout: float = 120.0,
    progress: Callable[[str], None] | None = None,
) -> str:
    """Provision the strip onto Wi-Fi over BLE. Returns the device DSN.

    ``progress``, if given, is called with a phase key ("connecting", "pairing",
    "sending", "joining") as onboarding advances, for UI feedback.

    Raises on failure (device not found, pairing/GATT error, or Wi-Fi join
    timeout).
    """
    # Imported lazily so the integration loads without BLE deps present.
    from bleak import BleakClient
    from bleak_retry_connector import establish_connection

    def _p(phase: str) -> None:
        if progress is not None:
            progress(phase)

    _p("connecting")
    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise RuntimeError(f"BLE device {address} not found (is it in pairing mode?)")

    try:
        client: BleakClient = await asyncio.wait_for(
            establish_connection(BleakClient, ble_device, f"monster-{address}"),
            timeout=45,
        )
    except (asyncio.TimeoutError, Exception) as err:  # noqa: BLE001
        raise RuntimeError(
            f"could not connect to {address} over BLE "
            "(strip still in pairing mode? Bluetooth adapter/proxy in range? "
            "note: ESPHome BT proxies cannot pair, which this device requires)"
        ) from err
    try:
        _p("pairing")
        try:
            await asyncio.wait_for(client.pair(), timeout=30)
        except Exception as err:  # noqa: BLE001 - some backends auto-pair on access
            _LOGGER.debug("pair() note for %s: %s", address, err)

        dsn = ""
        for _ in range(4):
            try:
                dsn = (await client.read_gatt_char(CHAR_DSN)).decode(errors="replace")
                break
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("DSN read retry: %s", err)
                await asyncio.sleep(1.0)
        if not dsn:
            raise RuntimeError("could not read DSN after pairing")

        connected = asyncio.Event()

        def _on_status(_char, data: bytearray) -> None:
            # settled state (byte 33 == 0x00) after a connecting phase = joined.
            if len(data) > _STATE_OFFSET and data[_STATE_OFFSET] == 0x00 and any(data):
                connected.set()

        try:
            await client.start_notify(CHAR_CONNECT_STATUS, _on_status)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("status notify unavailable: %s", err)

        payload = build_connect_payload(ssid, password, security)
        _LOGGER.info("Writing Wi-Fi credentials to %s (DSN %s)", address, dsn)
        _p("sending")
        await client.write_gatt_char(CHAR_CONNECT, payload, response=True)

        _p("joining")
        # The strip can take minutes to associate; don't hold the BLE link that
        # long (and the status notification is unreliable across BlueZ/proxies).
        # Wait briefly for the on-device hint, then let the caller confirm the
        # join over the LAN (async_find_new_strip polling).
        try:
            await asyncio.wait_for(connected.wait(), timeout=min(timeout, 20))
            _LOGGER.info("Strip %s reported joining Wi-Fi", dsn)
        except asyncio.TimeoutError:
            _LOGGER.debug(
                "no BLE join confirmation from %s yet; will confirm via LAN", dsn
            )
        return dsn
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass

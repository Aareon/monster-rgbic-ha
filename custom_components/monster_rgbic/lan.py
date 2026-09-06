"""Ayla LAN-mode local control for Monster Smart Lighting (RGBIC).

Reverse-engineered from the Monster app. After a one-time cloud fetch of the
device's static ``lanip_key``, all control happens directly on the LAN:

* We run a small HTTP server the bulb connects back to.
* The bulb performs a key-exchange; both sides derive AES-256-CBC + HMAC-SHA256
  session keys (double-HMAC KDF off the lanip_key + the exchanged nonces).
* We register with the bulb (``POST /local_reg.json``); to push a command we
  ``PUT /local_reg.json`` with ``notify:1`` which makes the bulb poll
  ``commands.json``, and we answer with the encrypted datapoint.

Caveats:
* The bulb allows exactly **one** LAN controller at a time. If the Monster
  phone app is holding the session, registration returns HTTP 503 and we fall
  back to the cloud.
* Only one property per command; ``color_select`` is only visible in
  ``mode:"color"``.

The crypto here was verified to reproduce the app's captured ciphertext
byte-for-byte.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import random
import socket
import string
import time
from typing import Any

import aiohttp
from aiohttp import web
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

LOCAL_PORT = 8899
REG_TIMEOUT = aiohttp.ClientTimeout(total=10)


def _rand_token(n: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))


class _Session:
    """Holds the derived cipher state for one LAN session."""

    def __init__(self, lan_key: str) -> None:
        self._lan = lan_key.encode()
        self._enc: Any = None
        self._dec: Any = None
        self._app_sign: bytes = b""
        self._dev_sign: bytes = b""
        self.seq = 0
        self.active = False

    def _kdf(self, r1: bytes, r2: bytes, t1: bytes, t2: bytes, suffix: int,
             swap: bool) -> bytes:
        base = (r2 + r1 + t2 + t1 if swap else r1 + r2 + t1 + t2) + bytes([suffix])
        inner = hmac.new(self._lan, base, hashlib.sha256).digest()
        return hmac.new(self._lan, inner + base, hashlib.sha256).digest()

    def derive(self, random_1: str, random_2: str, time_1: int, time_2: int) -> None:
        r1, r2 = random_1.encode(), random_2.encode()
        t1, t2 = str(time_1).encode(), str(time_2).encode()
        app_crypto = self._kdf(r1, r2, t1, t2, 0x31, False)
        app_iv = self._kdf(r1, r2, t1, t2, 0x32, False)[:16]
        self._app_sign = self._kdf(r1, r2, t1, t2, 0x30, False)
        dev_crypto = self._kdf(r1, r2, t1, t2, 0x31, True)
        dev_iv = self._kdf(r1, r2, t1, t2, 0x32, True)[:16]
        self._dev_sign = self._kdf(r1, r2, t1, t2, 0x30, True)
        self._enc = Cipher(algorithms.AES(app_crypto), modes.CBC(app_iv)).encryptor()
        self._dec = Cipher(algorithms.AES(dev_crypto), modes.CBC(dev_iv)).decryptor()
        self.seq = 0
        self.active = True

    def encapsulate(self, payload: str) -> str:
        s = '{"seq_no":%d,"data":%s}' % (self.seq, payload)
        self.seq += 1
        b = s.encode()
        sign = base64.b64encode(
            hmac.new(self._app_sign, b, hashlib.sha256).digest()
        ).decode()
        total = ((len(b) + 1 + 15) // 16) * 16
        ct = self._enc.update(b + b"\x00" * (total - len(b)))
        return '{"enc":"%s","sign":"%s"}' % (base64.b64encode(ct).decode(), sign)

    def decrypt(self, enc: str) -> str:
        pt = self._dec.update(base64.b64decode(enc)).rstrip(b"\x00")
        return pt.decode("utf-8", "replace")


class MonsterLanController:
    """Manages a LAN session with one Monster RGBIC bulb."""

    def __init__(self, api: Any, dsn: str, device_ip: str | None = None) -> None:
        self._api = api  # MonsterAylaApi, used only to fetch the lanip_key
        self._dsn = dsn
        self._device_ip = device_ip
        self._session: _Session | None = None
        self._runner: web.AppRunner | None = None
        self._local_ip: str | None = None
        self._pending: tuple[str, Any, str] | None = None
        self._served = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._session is not None and self._session.active

    # ---- lifecycle ----------------------------------------------------

    async def async_start(self) -> bool:
        """Fetch the LAN key, start the server, and register with the bulb.

        Returns True on success, False if LAN mode is unavailable (e.g. the
        app holds the session, or no LAN IP / key).
        """
        info = await self._api.async_get_lan_info(self._dsn)
        lan_key = info.get("lanip_key")
        self._device_ip = self._device_ip or info.get("lan_ip")
        if not lan_key or not self._device_ip:
            _LOGGER.debug("LAN unavailable for %s (key/ip missing)", self._dsn)
            return False

        self._session = _Session(lan_key)
        self._local_ip = self._detect_local_ip(self._device_ip)

        app = web.Application()
        app.router.add_post("/local_lan/key_exchange.json", self._h_key_exchange)
        app.router.add_get("/local_lan/commands.json", self._h_commands)
        app.router.add_post("/local_lan/property/datapoint.json", self._h_datapoint)
        app.router.add_post("/local_lan/property/datapoint/ack.json", self._h_datapoint)
        app.router.add_route("*", "/{tail:.*}", self._h_default)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", LOCAL_PORT)
        await site.start()

        if not await self._register(0, "post"):
            await self.async_stop()
            return False
        # Give the bulb a moment to key-exchange + post its initial state.
        for _ in range(30):
            if self.available:
                break
            await asyncio.sleep(0.2)
        return self.available

    async def async_stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._session = None

    # ---- control ------------------------------------------------------

    async def async_set_property(self, name: str, value: Any, base_type: str) -> bool:
        """Push one property to the bulb over the LAN. Returns True if served."""
        if not self.available:
            return False
        async with self._lock:
            self._pending = (name, value, base_type)
            self._served.clear()
            if not await self._register(1, "put"):  # notify -> bulb polls
                self._pending = None
                return False
            try:
                await asyncio.wait_for(self._served.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._pending = None
                return False
            return True

    # ---- HTTP handlers (bulb -> us) -----------------------------------

    async def _h_key_exchange(self, request: web.Request) -> web.Response:
        assert self._session is not None
        body = await request.json()
        ke = body.get("key_exchange", body)
        random_1 = ke.get("random_1")
        time_1 = ke.get("time_1")
        random_2 = _rand_token(len(random_1) if random_1 else 16)
        time_2 = int(time.time() * 10000)
        self._session.derive(random_1, random_2, time_1, time_2)
        resp = json.dumps({"random_2": random_2, "time_2": time_2},
                          separators=(",", ":"))
        return self._json(resp)

    async def _h_commands(self, request: web.Request) -> web.Response:
        assert self._session is not None
        if self._pending is not None:
            name, value, base_type = self._pending
            self._pending = None
            prop = {"property": {"base_type": base_type, "dsn": self._dsn,
                                 "echo": "none", "metadata": {"echo": "none"},
                                 "name": name, "value": value}}
            payload = json.dumps({"properties": [prop]}, separators=(",", ":"))
            self._served.set()
            return self._json(self._session.encapsulate(payload))
        return self._json(self._session.encapsulate("{}"))

    async def _h_datapoint(self, request: web.Request) -> web.Response:
        # Bulb pushing its state / acking; decrypt for debugging, ack empty.
        if self._session is not None and self._session.active:
            try:
                obj = await request.json()
                _LOGGER.debug("LAN state from %s: %s", self._dsn,
                              self._session.decrypt(obj["enc"]))
            except Exception:  # noqa: BLE001
                pass
        return web.Response(text="", content_type="application/json",
                            headers={"Connection": "keep-alive"})

    async def _h_default(self, request: web.Request) -> web.Response:
        return self._json("{}")

    @staticmethod
    def _json(text: str) -> web.Response:
        return web.Response(text=text, content_type="application/json",
                            headers={"Connection": "keep-alive"})

    # ---- helpers ------------------------------------------------------

    async def _register(self, notify: int, method: str) -> bool:
        reg = {"local_reg": {"ip": self._local_ip, "notify": notify,
                             "port": LOCAL_PORT, "uri": "/local_lan"}}
        url = f"http://{self._device_ip}/local_reg.json"
        try:
            async with aiohttp.ClientSession() as s:
                fn = s.post if method == "post" else s.put
                async with fn(url, json=reg, timeout=REG_TIMEOUT) as resp:
                    if resp.status == 503:
                        _LOGGER.info(
                            "Bulb %s busy (503) - another LAN controller (the "
                            "Monster app?) holds the session; using cloud",
                            self._dsn,
                        )
                        return False
                    return resp.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.debug("local_reg to %s failed: %s", self._device_ip, err)
            return False

    @staticmethod
    def _detect_local_ip(device_ip: str) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((device_ip, 80))
            return s.getsockname()[0]
        finally:
            s.close()

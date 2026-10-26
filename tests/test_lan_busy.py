"""MonsterLanController against a fake bulb that answers 503 to the notify PUT.

Run:  uv run --with aiohttp --with cryptography --with pytest pytest tests -q
(The fake bulb listens on a local port; no real bulb, no Home Assistant.)
"""
import asyncio
import importlib.util
import pathlib
import socket
import sys
import time

import aiohttp
from aiohttp import web

# lan.py needs nothing from Home Assistant, so load it without importing the package's __init__.
_LAN = pathlib.Path(__file__).parent.parent / "custom_components" / "monster_rgbic" / "lan.py"
_spec = importlib.util.spec_from_file_location("monster_lan_under_test", _LAN)
lan = importlib.util.module_from_spec(_spec)
sys.modules["monster_lan_under_test"] = lan
_spec.loader.exec_module(lan)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeBulb:
    """Answers local_reg like a bulb: POST starts a key exchange; PUT notify makes it poll."""

    def __init__(self, ctrl_port: int, busy_puts: int = 0, lapsed: bool = False,
                 always_503: bool = False) -> None:
        self.ctrl_port = ctrl_port
        self.busy_puts = busy_puts  # answer this many PUTs with 503, then work
        self.lapsed = lapsed  # 503 to every PUT until a POST (re-register) arrives
        self.always_503 = always_503
        self.posts = 0
        self.puts = 0
        self.served = 0
        self.port = _free_port()
        self._runner = None
        self._tasks = []

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/local_reg.json", self._post)
        app.router.add_put("/local_reg.json", self._put)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, "127.0.0.1", self.port).start()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self._runner.cleanup()

    async def _post(self, request: web.Request) -> web.Response:
        self.posts += 1
        if self.always_503:
            return web.Response(status=503)
        self.lapsed = False
        self._tasks.append(asyncio.create_task(self._key_exchange()))
        return web.Response(text="{}", content_type="application/json")

    async def _put(self, request: web.Request) -> web.Response:
        self.puts += 1
        if self.always_503 or self.lapsed:
            return web.Response(status=503)
        if self.busy_puts > 0:
            self.busy_puts -= 1
            return web.Response(status=503)
        self._tasks.append(asyncio.create_task(self._poll()))
        return web.Response(text="{}", content_type="application/json")

    async def _key_exchange(self) -> None:
        url = f"http://127.0.0.1:{self.ctrl_port}/local_lan/key_exchange.json"
        async with aiohttp.ClientSession() as s:
            await s.post(url, json={"key_exchange": {"random_1": "r" * 16, "time_1": 1}})

    async def _poll(self) -> None:
        url = f"http://127.0.0.1:{self.ctrl_port}/local_lan/commands.json"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as resp:
                await resp.read()
        self.served += 1


class FakeApi:
    async def async_get_lan_info(self, dsn):
        return {"lanip_key": "k" * 32, "lan_ip": "127.0.0.1"}


async def _make(**bulb_kwargs):
    ctrl_port = _free_port()
    bulb = FakeBulb(ctrl_port, **bulb_kwargs)
    await bulb.start()
    ctrl = lan.MonsterLanController(FakeApi(), "AC000W000000001", "127.0.0.1",
                                    port=ctrl_port, device_port=bulb.port)
    assert await ctrl.async_start()
    return bulb, ctrl


def _run(coro):
    return asyncio.run(coro)


def test_works_when_the_bulb_is_not_busy(monkeypatch):
    async def go():
        bulb, ctrl = await _make()
        try:
            assert await ctrl.async_set_property("brightness", 50, "integer")
            await asyncio.sleep(0.1)  # the fake bulb counts a poll after it has read the reply
            assert bulb.puts == 1 and bulb.served == 1
        finally:
            await ctrl.async_stop()
            await bulb.stop()
    _run(go())


def test_retries_a_transient_503_and_stays_on_the_lan(monkeypatch):
    monkeypatch.setattr(lan, "BUSY_BACKOFF", 0.01)

    async def go():
        bulb, ctrl = await _make()
        bulb.busy_puts = 2  # after start-up, so the first two PUTs answer 503
        try:
            assert await ctrl.async_set_property("brightness", 50, "integer")
            await asyncio.sleep(0.1)
            assert bulb.puts == 3 and bulb.served == 1
            assert bulb.posts == 1  # only the start-up registration, no re-register needed
            assert ctrl.available
        finally:
            await ctrl.async_stop()
            await bulb.stop()
    _run(go())


def test_reregisters_when_the_session_has_lapsed(monkeypatch):
    monkeypatch.setattr(lan, "BUSY_BACKOFF", 0.01)

    async def go():
        bulb, ctrl = await _make()
        bulb.lapsed = True  # the session lapses after start-up: every PUT answers 503
        try:
            assert await ctrl.async_set_property("mode", "color", "string")
            await asyncio.sleep(0.1)
            assert bulb.posts == 2  # start-up plus the re-register
            assert bulb.served == 1
            assert ctrl.available
        finally:
            await ctrl.async_stop()
            await bulb.stop()
    _run(go())


def test_gives_up_and_goes_to_the_cloud_for_a_while(monkeypatch):
    monkeypatch.setattr(lan, "BUSY_BACKOFF", 0.01)

    async def go():
        bulb, ctrl = await _make()
        bulb.always_503 = True
        try:
            assert not await ctrl.async_set_property("brightness", 50, "integer")
            assert not ctrl.available  # cooling down: later properties skip the LAN
            puts_after_failure = bulb.puts
            assert not await ctrl.async_set_property("brightness", 60, "integer")
            assert bulb.puts == puts_after_failure  # no new attempt during the cooldown
            # After the cooldown the LAN is tried again.
            ctrl._cooldown_until = time.monotonic() - 1
            bulb.always_503 = False
            assert ctrl.available
            assert await ctrl.async_set_property("brightness", 70, "integer")
        finally:
            await ctrl.async_stop()
            await bulb.stop()
    _run(go())

"""BlueZ NoInputNoOutput pairing agent for Monster RGBIC BLE onboarding.

The strips require a Just-Works bond, but a headless BlueZ (Home Assistant OS) has
no pairing agent registered, so bleak's ``pair()`` fails Just-Works bonding with
``org.bluez.Error.AuthenticationFailed``. Registering an auto-accepting
NoInputNoOutput agent — exactly what ``bluetoothctl`` does, which pairs these
strips fine — lets the bond complete. On Windows the OS supplies this agent
automatically, which is why the desktop tool never needed it.

This lives in its own module deliberately WITHOUT ``from __future__ import
annotations`` so dbus-fast's ``@method()`` signature annotations ("o", "s") are the
literal signature strings it expects, not lazily-stringized future annotations.
"""

import logging

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/org/bluez/monster_rgbic_agent"


async def register_pairing_agent():
    """Best-effort: register an auto-accepting NoInputNoOutput BlueZ agent.

    Returns an opaque handle for :func:`unregister_pairing_agent`, or ``None`` if
    it could not be registered (pairing then falls back to any existing agent).
    """
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
        from dbus_fast.service import ServiceInterface, method
    except Exception as err:  # noqa: BLE001 - dbus-fast is present via bleak on HAOS
        _LOGGER.debug("dbus-fast unavailable; no pairing agent: %s", err)
        return None

    try:

        class _Agent(ServiceInterface):
            def __init__(self):
                super().__init__("org.bluez.Agent1")

            @method()
            def Release(self):  # noqa: N802
                pass

            @method()
            def RequestAuthorization(self, device: "o"):  # noqa: N802
                # Accept the Just-Works pairing (no user confirmation available).
                return

            @method()
            def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802
                return

            @method()
            def Cancel(self):  # noqa: N802
                pass

        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(AGENT_PATH, _Agent())
        intro = await bus.introspect("org.bluez", "/org/bluez")
        obj = bus.get_proxy_object("org.bluez", "/org/bluez", intro)
        mgr = obj.get_interface("org.bluez.AgentManager1")
        await mgr.call_register_agent(AGENT_PATH, "NoInputNoOutput")
        try:
            await mgr.call_request_default_agent(AGENT_PATH)
        except Exception as err:  # noqa: BLE001 - non-fatal if another agent is default
            _LOGGER.debug("request-default-agent note: %s", err)
        _LOGGER.debug("registered NoInputNoOutput pairing agent")
        return (bus, mgr)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("pairing agent registration failed (continuing): %s", err)
        return None


async def unregister_pairing_agent(handle):
    """Tear down the agent registered by :func:`register_pairing_agent`."""
    if not handle:
        return
    bus, mgr = handle
    try:
        await mgr.call_unregister_agent(AGENT_PATH)
    except Exception:  # noqa: BLE001
        pass
    try:
        bus.disconnect()
    except Exception:  # noqa: BLE001
        pass

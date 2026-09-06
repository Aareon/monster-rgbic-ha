# Monster Smart Lighting (RGBIC) for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A cloud‑polling Home Assistant integration for **Monster Smart Lighting** RGBIC
devices — the ones controlled by the `com.xtreme.monstersmartlighting` app, which
run on the **Ayla Networks** IoT cloud behind Monster's own "Copilot" backend.

You sign in with **your Monster app email + password**; the integration
reproduces the app's authentication flow directly (no app, no phone, no
certificate tricks):

1. `POST api.monstergen2.bycopilot.com/v4/auth/login` → Copilot access token
2. `POST sphere.bycopilot.com/v2/partner/<partnerId>/acquire_ticket` → partner ticket
3. `POST user-field.aylanetworks.com/api/v1/token_sign_in` → Ayla session
4. Ayla device API for state + control

## Features

- ✅ On / off
- ✅ Brightness
- ✅ RGB color
- ✅ **Local (LAN) control** — direct, offline‑capable control (see below)
- 🔜 Effects (Rainbow, Fire, Confetti… — dozens of built‑in scenes)
- 🔜 White / color‑temperature mode
- 🔜 Per‑IC control

## Local (LAN) control

With **“Use local (LAN) control”** enabled (default), the integration fetches
each bulb’s static `lanip_key` from the cloud **once**, then drives the bulbs
**directly on your LAN** using Ayla’s LAN protocol — fast and functional even if
the internet is down. State is still polled via the cloud; writes go local with
an automatic cloud fallback.

**Important limitations:**
- The bulb allows **one local controller at a time.** While Home Assistant holds
  the LAN session, the **Monster phone app can’t connect locally** to that bulb
  (and vice‑versa). If the app is holding it, HA logs a notice and uses the cloud.
- Home Assistant must be reachable by the bulb on the LAN (each bulb connects
  back to HA on its own TCP port, starting at **8899**, then 8900, 8901, …).
- Set one property at a time (the integration already does this).

## Installation

### HACS (custom repository)

This integration isn't in the default HACS store — add it as a **custom
repository**:

1. In Home Assistant, open **HACS**.
2. Click the **⋮** menu (top‑right) → **Custom repositories**.
3. **Repository:** `https://github.com/Aareon/monster-rgbic-ha`
4. **Type / Category:** **Integration** → click **Add**.
5. Search HACS for **Monster Smart Lighting (RGBIC)**, click **Download**, then
   **restart Home Assistant**.
6. Configure it via **Settings → Devices & Services → Add Integration** (below).

### Manual

Copy `custom_components/monster_rgbic/` into your Home Assistant
`config/custom_components/` folder and restart. On Home Assistant OS, use the
**Samba** or **Advanced SSH & Web Terminal** add‑on to place the files.

## Setup

**Settings → Devices & Services → Add Integration → “Monster Smart Lighting”**,
then enter your Monster app email + password. Each strip appears as a light
entity with on/off, brightness, and color.

## Multiple bulbs

**Fully supported.** The integration enumerates every Monster device on your
account and creates a separate light entity and HA device for each — including
several bulbs or strips **of the same model**. Local (LAN) control scales too:
each bulb gets its own local port (8899, 8900, 8901, …), so any number of bulbs
can be driven locally at the same time.

### Adding another bulb later

Devices are discovered **when the integration loads**, so a bulb added after
setup is **not auto‑detected** — you need one reload:

1. **Pair the new bulb in the Monster app first.** The integration reads your
   Ayla account; it doesn't do Wi‑Fi onboarding. Adding the bulb in the app puts
   it on the same account these credentials use.
2. In Home Assistant, **reload the integration**: Settings → Devices & Services →
   **Monster Smart Lighting** → ⋮ → **Reload** (or restart Home Assistant).
3. The new bulb appears as its own light entity and device (and gets its own LAN
   port if local control is on).

## Notes

- **Region:** hard‑coded to the US "Field" Ayla cluster (matches the extracted
  app config). EU accounts would need the `-eu` hosts — open an issue if you need
  that.
- **Credentials** are stored in the Home Assistant config entry, like any other
  cloud integration, and are only sent to Monster/Ayla.
- The Ayla session (~24 h) is refreshed automatically.

## How this was built (transparency)

This integration was developed collaboratively with **Anthropic's Claude**
(via Claude Code). That includes reverse‑engineering Monster's undocumented,
certificate‑pinned cloud authentication **and** the Ayla LAN‑mode protocol, plus
writing all of the code here. The work was grounded in real device traffic — the
LAN crypto was verified to reproduce the app's captured packets byte‑for‑byte,
and the result was tested live against actual hardware. Noted here in the
interest of full transparency about how the code was produced.

## Disclaimer

This is an **unofficial** integration, not affiliated with or endorsed by Monster,
Jem Accessories, or Ayla Networks. It was built by reverse‑engineering the
official Android app for personal interoperability with hardware you own. Use at
your own risk.

## License

[MIT](LICENSE)

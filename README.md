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
- Home Assistant must be reachable by the bulb on the LAN (the bulb connects back
  to HA on TCP port **8899**).
- Set one property at a time (the integration already does this).

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → add this repo's URL, category
   **Integration**.
2. Install **Monster Smart Lighting (RGBIC)**, then restart Home Assistant.

### Manual

Copy `custom_components/monster_rgbic/` into your Home Assistant
`config/custom_components/` folder and restart. On Home Assistant OS, use the
**Samba** or **Advanced SSH & Web Terminal** add‑on to place the files.

## Setup

**Settings → Devices & Services → Add Integration → “Monster Smart Lighting”**,
then enter your Monster app email + password. Each strip appears as a light
entity with on/off, brightness, and color.

## Notes

- **Region:** hard‑coded to the US "Field" Ayla cluster (matches the extracted
  app config). EU accounts would need the `-eu` hosts — open an issue if you need
  that.
- **Credentials** are stored in the Home Assistant config entry, like any other
  cloud integration, and are only sent to Monster/Ayla.
- The Ayla session (~24 h) is refreshed automatically.

## Disclaimer

This is an **unofficial** integration, not affiliated with or endorsed by Monster,
Jem Accessories, or Ayla Networks. It was built by reverse‑engineering the
official Android app for personal interoperability with hardware you own. Use at
your own risk.

## License

[MIT](LICENSE)

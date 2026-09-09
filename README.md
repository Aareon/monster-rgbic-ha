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
- ✅ **Effects** — the bulb's built‑in scenes (Rainbow, Fire, Confetti…), exposed
  as a Home Assistant effect list (see below)
- ✅ **Per‑IC segments** — paint sections of the strip by IC index via the
  `monster_rgbic.set_segments` service (see below)
- ✅ **Custom animated effects** — supply a color palette and let the bulb
  animate it on‑device via `monster_rgbic.set_custom_effect` (see below)
- ✅ **Local (LAN) control** — direct, offline‑capable control (see below)
- ✅ **Bluetooth onboarding** — set up a brand‑new strip's Wi‑Fi from Home
  Assistant, no Monster app required (see below)
- 🔜 White / color‑temperature mode

## Effects (built‑in scenes)

The bulbs ship with banks of built‑in patterns — **static** looks (Candle,
Neon, Patriotic…), **dynamic** animations (Rainbow, Fire, Confetti, Vortex…),
**music‑reactive** modes (Soundwave, Equalizer…), and your **DIY** scenes from
the app. The integration reads these banks straight off each device and exposes
them as Home Assistant's standard **effect list** on the light card, labelled by
family (e.g. `Dynamic: Rainbow`, `Static: Candle`, `Music: Soundwave 1`,
`DIY: Blink`).

Pick one from the effect dropdown, or set it in an automation:

```yaml
service: light.turn_on
target:
  entity_id: light.xtreme_rgbic_ls_1
data:
  effect: "Dynamic: Rainbow"
```

The scene list is read per device, so DIY scenes (and any you've renamed in the
app) show up with their current names. Selecting an RGB color switches the bulb
back to solid‑colour mode.

## Per‑IC segments (custom presets)

RGBIC strips can address each LED "IC" individually. This integration exposes
that through the **`monster_rgbic.set_segments`** service: you give it a list of
segments — each an inclusive range of IC indices and an RGB color — and it
paints them, stores the result as one of the strip's per‑IC presets, and
activates it. ICs you don't cover turn off (or take a `background` color).

```yaml
service: monster_rgbic.set_segments
target:
  entity_id: light.xtreme_rgbic_ls_1
data:
  segments:
    - start: 0
      end: 14
      rgb: [255, 0, 0]     # first 15 ICs red
    - start: 15
      end: 29
      rgb: [0, 0, 255]     # next 15 ICs blue
  background: [0, 0, 0]     # remaining ICs off (optional)
  brightness: 100           # optional, 1-100
  slot: 0                   # optional, which preset slot (0-4)
  name: "HA Custom"         # optional
```

IC indices are 0‑based; the strip's IC count is read from the device
(`no_of_rgbics`). The preset is stored in slot `0` (`pic00`) by default, so it
also shows up in the effect dropdown as `Per-IC: <name>` for one‑tap re‑use.
The encoding was reverse‑engineered from a captured preset and is reproduced
byte‑for‑byte.

## Custom animated effects

Beyond the built‑in scenes, you can hand the bulb your **own palette** and have
it animate it **on‑device** via **`monster_rgbic.set_custom_effect`**. Because
the animation runs on the bulb's own microcontroller (not streamed frame‑by‑
frame from Home Assistant), it's smooth and fast — well past the ~6 fps ceiling
that limits externally‑streamed per‑IC animation.

```yaml
service: monster_rgbic.set_custom_effect
target:
  entity_id: light.xtreme_rgbic_ls_1
data:
  colors:
    - [255, 0, 255]   # magenta
    - [0, 255, 255]   # cyan
    - [255, 128, 0]   # orange
  style: Tracer       # motion style (see below)
  speed: 80           # 1 (slow) - 100 (fast)
  brightness: 100     # optional, 1-100
```

`style` selects the motion — `Blink`, `Breath`, `Tracer`, `Color Wipe`,
`Confetti`, `Blue Fire`, `RGB Chase`, `Color Run`, `Color Flow`, `Marquee`. Each
style maps to one of the strip's **DIY preset slots**, so running a custom effect
**overwrites that slot's stored preset** — exactly as editing that DIY effect in
the app would. The effect then also appears in the effect dropdown as
`DIY: <name>` for one‑tap reuse.

> **Streamed vs. on‑device:** `set_segments` streams exact per‑IC frames from HA
> (great for static layouts and slow animation, but capped at ~6 fps by the
> bulb's command‑poll rate). `set_custom_effect` offloads the animation to the
> bulb for fast, smooth motion, at the cost of using the built‑in motion styles
> rather than arbitrary per‑frame control.

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

## Bluetooth onboarding (no Monster app)

You can provision a **brand‑new** strip's Wi‑Fi straight from Home Assistant —
the Monster app is not needed at all. This requires a **Bluetooth adapter** on
your Home Assistant host (the built‑in Bluetooth integration).

1. Put the strip into **pairing/setup mode** (the blinking state it ships in, or
   after a factory reset) and keep it near the HA Bluetooth adapter.
2. **Settings → Devices & Services → Add Integration → Monster Smart Lighting**,
   then choose **"Set up a new strip over Bluetooth."**
3. Pick the strip, enter your **Wi‑Fi** SSID/password and (if not already set up)
   your **Monster account** — then submit.

Home Assistant connects over BLE, pairs, sends the Wi‑Fi credentials (with an
8‑character setup token), waits for the strip to join, confirms it has checked in
to Ayla (the `connected.json` gate), then claims it to your account.

> **After onboarding, the strip flashes in pairing mode until it receives one
> command.** A freshly‑claimed strip (and any strip after a **power‑cycle**) boots
> into `mode:'pair'` — flashing, ignoring commands — until it gets a single control
> command. Toggle it or set a color from Home Assistant once and it snaps into
> normal operation. If a strip is stuck flashing after a power loss, that first HA
> command (or an automation) wakes it.

**What's local vs. cloud:** the Wi‑Fi provisioning and the registration token are
handled **entirely locally** (BLE + the strip's own LAN endpoint). The final
device **claim** is the one required call to Ayla's cloud — that's what
provisions the LAN key used for local control afterward. So this removes the
Monster app from setup, but not Ayla's cloud (that isn't possible on this
hardware — the LAN key doesn't exist on the strip until it's claimed).

> The BLE setup protocol (GATT service `1CF0FE66` / `FE28`, a 105‑byte
> credentials write, Just‑Works pairing) was reverse‑engineered from the app and
> validated by provisioning real hardware. Only **2.4 GHz** Wi‑Fi is supported by
> the strips.

### Adding another bulb later

Devices are discovered **when the integration loads**, so a bulb added after
setup is **not auto‑detected** — you need one reload:

1. **Get the new bulb onto your account** — either pair it in the Monster app,
   or use this integration's **Bluetooth onboarding** (above), which adds it to
   the same account without the app. Either way it ends up on the account these
   credentials use.
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

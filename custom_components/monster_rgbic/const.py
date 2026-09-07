"""Constants for the Monster Smart Lighting (RGBIC) integration.

All values here were reverse-engineered from the Monster Smart Lighting Android
app. The bulbs are on the Ayla Networks IoT cloud, but the app authenticates via
Monster's own "Copilot" (bycopilot.com) backend and exchanges a partner ticket
for an Ayla session (OEM partner SSO). This integration reproduces that chain.
"""

from __future__ import annotations

DOMAIN = "monster_rgbic"

# --- Monster "Copilot" backend ---
COPILOT_BASE = "https://api.monstergen2.bycopilot.com"
SPHERE_BASE = "https://sphere.bycopilot.com"
COPILOT_APPLICATION_ID = "MONSTERGEN2"
COPILOT_PARTNER_ID = "162fa71e-46d6-4cc6-9eab-db1925fdcb30"

# --- Ayla (US "Field" region) ---
AYLA_USER_BASE = "https://user-field.aylanetworks.com"
AYLA_ADS_BASE = "https://ads-field.aylanetworks.com"
AYLA_APP_ID = "RGBIC-yQ-id"
AYLA_APP_SECRET = "RGBIC-O7v7HvMh9OjQBz8eA6tL6Pprp8U"

# --- Config entry keys ---
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_LOCAL = "local_control"  # prefer LAN-mode for writes (see lan.py)

# --- Device datapoint (property) names ---
PROP_POWER = "power"                # boolean
PROP_MODE = "mode"                  # str: color/white/static/dynamic/per_ic
PROP_BRIGHTNESS = "brightness"      # int 0-100
PROP_COLOR_SELECT = "color_select"  # int packed R<<16 | G<<8 | B
PROP_COLOR_BRIGHT = "color_bright"  # int 0-100
PROP_COLOR_SAT = "color_saturation"  # int 0-100
PROP_NUM_ICS = "no_of_rgbics"        # int: addressable IC count for this strip
PROP_MAX_ICS = "max_no_of_rgbics"    # int: hardware max IC count
PROP_PER_IC_PAT = "per_ic_pat"       # int: which pic slot is active

MODE_COLOR = "color"
MODE_PER_IC = "per_ic"

# Per-IC preset slots (custom "paint each IC" presets), pic00..pic04.
PER_IC_SLOTS = 5

# --- Effects (built-in scenes) ---
# The bulb groups its patterns into "mode" families; within a family a
# <family>_pat integer selects which slot plays. Each slot is a property
# (e.g. "dyn03") whose JSON value carries the scene's display name in "n".
# Verified live: setting mode + <family>_pat plays the built-in scene, and the
# _pat index equals the slot number.
#   mode -> (slot prefix, selector property, human family label)
# NB: the mode value is what the device reports/accepts. All families are
# lowercase EXCEPT "DIY", which the firmware spells uppercase (verified from the
# app's own traffic and on hardware) -- sending "diy" is silently ignored.
EFFECT_FAMILIES: dict[str, tuple[str, str, str]] = {
    "static": ("st", "st_pat", "Static"),
    "dynamic": ("dyn", "dyn_pat", "Dynamic"),
    "music": ("mus", "mus_pat", "Music"),
    "DIY": ("diy", "diy_pat", "DIY"),
    "per_ic": ("pic", "per_ic_pat", "Per-IC"),
}
# Up to 16 slots per family (00..15).
EFFECT_MAX_SLOTS = 16

# --- Custom on-device effects (DIY slots) ---
# A DIY slot animates a custom color palette on the bulb's own MCU at native
# refresh (far past the ~6 fps ceiling for externally-streamed frames). The
# motion *style* is bound to the slot index; the palette (ca) and speed (s) are
# what you customize. These are each slot's default/shipped style name.
MODE_DIY = "DIY"
PROP_DIY_PAT = "diy_pat"
DIY_STYLES: dict[str, int] = {
    "Blink": 0,
    "Breath": 1,
    "Tracer": 2,
    "Color Wipe": 3,
    "Confetti": 4,
    "Blue Fire": 5,
    "RGB Chase": 6,
    "Color Run": 7,
    "Color Flow": 8,
    "Marquee": 9,
}

# Ayla session lifetime is ~24h; refresh a bit early.
DEFAULT_SCAN_INTERVAL = 30  # seconds

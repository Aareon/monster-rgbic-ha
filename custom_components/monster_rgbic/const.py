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

# --- Device datapoint (property) names ---
PROP_POWER = "power"                # boolean
PROP_MODE = "mode"                  # str: color/white/static/dynamic/per_ic
PROP_BRIGHTNESS = "brightness"      # int 0-100
PROP_COLOR_SELECT = "color_select"  # int packed R<<16 | G<<8 | B
PROP_COLOR_BRIGHT = "color_bright"  # int 0-100
PROP_COLOR_SAT = "color_saturation"  # int 0-100

MODE_COLOR = "color"

# Ayla session lifetime is ~24h; refresh a bit early.
DEFAULT_SCAN_INTERVAL = 30  # seconds

"""Per-IC ("custom preset") color encoding for Monster RGBIC strips.

Reverse-engineered from the app and verified byte-for-byte against a captured
preset. A per-IC preset stores one entry per IC, in order, as a variable-length
stream that is then base64-encoded into the ``ca_b64`` field of a ``picNN`` slot:

* an **off** IC is a single ``0x00`` byte
* a **lit** IC is four bytes: ``0xE4 R G B`` (a constant 0xE4 marker, then RGB)

Because the marker (0xE4) is never 0x00, a decoder can tell the two apart while
walking the stream. The total number of entries equals the strip's IC count
(``no_of_rgbics``).
"""

from __future__ import annotations

import base64

# Constant first byte the firmware writes before each lit IC's RGB triple. It
# doubles as the "this is a 4-byte color entry" marker (vs. 0x00 = off).
MARKER = 0xE4

# A per-IC color: an (r, g, b) tuple, or None for an off/black IC.
Color = tuple[int, int, int]


def encode(colors: list[Color | None]) -> str:
    """Encode a per-IC color list to the ``ca_b64`` base64 string."""
    out = bytearray()
    for c in colors:
        if c is None:
            out.append(0x00)
        else:
            r, g, b = c
            out += bytes([MARKER, r & 0xFF, g & 0xFF, b & 0xFF])
    return base64.b64encode(bytes(out)).decode()


def decode(ca_b64: str) -> list[Color | None]:
    """Decode a ``ca_b64`` string back to a per-IC color list (inverse of
    :func:`encode`). Trailing padding bytes are ignored."""
    raw = base64.b64decode(ca_b64) if ca_b64 else b""
    colors: list[Color | None] = []
    i = 0
    while i < len(raw):
        if raw[i] == MARKER and i + 3 < len(raw):
            colors.append((raw[i + 1], raw[i + 2], raw[i + 3]))
            i += 4
        else:
            colors.append(None)  # 0x00 (or stray padding) = off
            i += 1
    return colors

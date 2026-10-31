"""Read or bump the integration version in custom_components/monster_rgbic/manifest.json.

    python3 scripts/release.py version          print the current version
    python3 scripts/release.py bump patch       write the next patch (or minor, major) and print it

The file is edited in place with a regex so its formatting and key order stay as they are.
"""

import pathlib
import re
import sys

MANIFEST = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "monster_rgbic" / "manifest.json"
VERSION_RE = re.compile(r'("version"\s*:\s*")(\d+)\.(\d+)\.(\d+)(")')


def read() -> tuple[int, int, int]:
    m = VERSION_RE.search(MANIFEST.read_text(encoding="utf-8"))
    if not m:
        sys.exit(f"{MANIFEST}: no X.Y.Z \"version\" found")
    return int(m[2]), int(m[3]), int(m[4])


def bump(level: str) -> str:
    major, minor, patch = read()
    if level == "major":
        major, minor, patch = major + 1, 0, 0
    elif level == "minor":
        minor, patch = minor + 1, 0
    elif level == "patch":
        patch += 1
    else:
        sys.exit(f"unknown level {level!r}: use patch, minor or major")
    new = f"{major}.{minor}.{patch}"
    text = MANIFEST.read_text(encoding="utf-8")
    MANIFEST.write_text(VERSION_RE.sub(lambda m: f"{m[1]}{new}{m[5]}", text, count=1), encoding="utf-8", newline="\n")
    return new


def main(argv: list[str]) -> None:
    if argv[:1] == ["version"] and len(argv) == 1:
        print("{}.{}.{}".format(*read()))
    elif argv[:1] == ["bump"] and len(argv) == 2:
        print(bump(argv[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])

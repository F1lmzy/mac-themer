"""Theme pack loading, validation and colour maths."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

PALETTE_KEYS = (
    "background",
    "foreground",
    "cursor",
    "accent",
    "selection_background",
    "selection_foreground",
) + tuple("color%d" % i for i in range(16))

BAR_COLOR_KEYS = ("background", "item_bg", "accent", "label", "icon", "muted", "red", "green", "yellow")


class ThemeError(Exception):
    """A theme pack is missing or malformed."""


def check_hex(value, where):
    if not isinstance(value, str) or not HEX.match(value):
        raise ThemeError("%s: expected #rrggbb, got %r" % (where, value))
    return value.lower()


def rgb(value):
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def hex_of(triple):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in triple)


def mix(a, b, t):
    """Blend two colours in sRGB; 0 returns a, 1 returns b.

    sRGB and not linear light: these are swatches chosen by eye next to each
    other, so the elevation ramp is mixed in the same space the palette was
    picked in, which keeps a derived step in the palette's own family.
    """
    ra, ga, ba = rgb(a)
    rb, gb, bb = rgb(b)
    return hex_of((ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t))


def alpha_byte(value):
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ThemeError("bar.background_alpha: expected 0.0-1.0, got %r" % (value,))
    return round(number * 255)


def argb(color, alpha=1.0):
    """0xAARRGGBB — the integer form bar and border consumers want."""
    r, g, b = rgb(color)
    return 0xFF000000 | (r << 16) | (g << 8) | b if alpha >= 1.0 else (
        (alpha_byte(alpha) << 24) | (r << 16) | (g << 8) | b
    )


@dataclass(frozen=True)
class Theme:
    slug: str
    name: str
    variant: str
    palette: dict
    border: dict
    token_overrides: dict
    bar: dict
    source: Path


def available(repo):
    """Slugs of every pack in the repo, sorted, ignoring half-made ones."""
    themes = Path(repo) / "themes"
    if not themes.is_dir():
        return []
    return sorted(p.name for p in themes.iterdir() if (p / "theme.toml").is_file())


def load(repo, slug):
    path = Path(repo) / "themes" / slug / "theme.toml"
    if not path.is_file():
        raise ThemeError("no theme pack %r in %s" % (slug, Path(repo) / "themes"))
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ThemeError("%s: %s" % (path, exc))

    palette_section = raw.get("palette")
    if not isinstance(palette_section, dict):
        raise ThemeError("%s: missing [palette]" % path)
    palette = {}
    for key in PALETTE_KEYS:
        if key not in palette_section:
            raise ThemeError("%s: palette.%s is required" % (path, key))
        palette[key] = check_hex(palette_section[key], "palette.%s" % key)
    for key in palette_section:
        if key not in PALETTE_KEYS:
            raise ThemeError("%s: palette.%s is not a known key" % (path, key))

    border_section = raw.get("border")
    if not isinstance(border_section, dict):
        raise ThemeError("%s: missing [border]" % path)
    border = {}
    for key in ("active", "inactive"):
        if key not in border_section:
            raise ThemeError("%s: border.%s is required" % (path, key))
        border[key] = check_hex(border_section[key], "border.%s" % key)

    tokens = {key: check_hex(value, "tokens.%s" % key)
              for key, value in (raw.get("tokens") or {}).items()}

    bar = {}
    for key, value in (raw.get("bar") or {}).items():
        if key == "background_alpha":
            alpha_byte(value)
            bar[key] = float(value)
        elif key in BAR_COLOR_KEYS:
            bar[key] = check_hex(value, "bar.%s" % key)
        else:
            raise ThemeError("%s: bar.%s is not a known key" % (path, key))

    name = raw.get("name") or slug
    if not isinstance(name, str):
        raise ThemeError("%s: name must be a string" % path)
    variant = raw.get("variant") or "dark"
    if variant not in ("dark", "light"):
        raise ThemeError("%s: variant must be dark or light" % path)

    return Theme(slug=slug, name=name, variant=variant, palette=palette,
                 border=border, token_overrides=tokens, bar=bar, source=path)

"""Theme pack loading, validation and colour maths."""
from __future__ import annotations

import os
import re
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# A slug is a directory name this code will accept as a pack identity. It is
# narrower than the filesystem on purpose, so a catalog that a consumer will
# parse can never carry a name that looks like a path or a URL.
SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")

# Hard ceilings for the read-only catalog. They bound the work one `catalog`
# call can do and match what consumers are expected to accept.
CATALOG_LIMIT = 128
MAX_THEME_BYTES = 65536

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
    """Slugs of every pack in the checkout at *repo*, sorted."""
    return packs(Path(repo) / "themes")


def packs(themes):
    """Slugs of every pack directly under *themes*, sorted, ignoring half-made ones.

    This is the collection `MACTHEMER_THEMES` names, which is where a pack is
    installed into as well: listing and installing must agree on one directory.
    """
    themes = Path(themes)
    if not themes.is_dir():
        return []
    return sorted(p.name for p in themes.iterdir() if (p / "theme.toml").is_file())


def load(repo, slug):
    return load_pack(Path(repo) / "themes", slug)


def load_pack(themes, slug):
    path = Path(themes) / slug / "theme.toml"
    if not path.is_file():
        raise ThemeError("no theme pack %r in %s" % (slug, Path(themes)))
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ThemeError("%s: %s" % (path, exc))
    return _build(raw, path, slug)


def check(raw, path, slug):
    """Validate a pack document that was built in memory, not read from disk.

    `catalog` and `load` validate what is on disk. This is the same check for a
    document an importer is about to write, so it cannot commit a pack the
    catalog would refuse a moment later.
    """
    return _build(raw, Path(path), slug)


def catalog(themes):
    """Every pack under *themes*, resolved, sorted by slug and strictly read.

    This is the discovery path behind `mac-themer catalog`. It is stricter
    than `available`/`load`: identities are validated, symlinks that leave the
    directory are refused, reads are bounded and regular-file-only, and a
    broken pack fails the whole catalog instead of publishing a partial one.
    A hidden entry or a regular file is not a pack and is ignored; every other
    directory is treated as one, so a half-made pack is an error, not a
    silently missing row.
    """
    themes = Path(themes)
    if not themes.is_dir():
        return []
    root = themes.resolve()
    try:
        listing = sorted(themes.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ThemeError("%s: %s" % (themes, exc))
    entries = []
    for entry in listing:
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        slug = entry.name
        if not SLUG.match(slug):
            raise ThemeError("invalid theme slug %r in %s" % (slug, themes))
        pack = _resolve(entry, "theme pack %r" % slug)
        if pack != root and root not in pack.parents:
            raise ThemeError("theme pack %r escapes %s" % (slug, themes))
        source = pack / "theme.toml"
        if not source.is_file():
            raise ThemeError("no theme pack %r in %s" % (slug, themes))
        resolved_source = _resolve(source, "theme pack %r source" % slug)
        if pack not in resolved_source.parents:
            raise ThemeError("theme pack %r reads outside its directory" % slug)
        theme = _parse(_read_bounded(resolved_source), source, slug)
        if not theme.name or len(theme.name.encode("utf-8")) > 256 or "\x00" in theme.name:
            raise ThemeError("theme pack %r name must be 1-256 bytes without NUL" % slug)
        entries.append(theme)
        if len(entries) > CATALOG_LIMIT:
            raise ThemeError("theme catalog has more than %d packs" % CATALOG_LIMIT)
    return entries


def _resolve(path, where):
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ThemeError("%s: %s" % (where, exc))


def _read_bounded(path):
    """Read a theme source without blocking and without unbounded input.

    Open the already-contained, resolved source without following a substituted
    symlink or waiting for a FIFO writer. Check the descriptor, not a prior stat.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ThemeError("%s: not a regular file" % path)
            if info.st_size > MAX_THEME_BYTES:
                raise ThemeError("%s: larger than %d bytes" % (path, MAX_THEME_BYTES))
            data = handle.read(MAX_THEME_BYTES + 1)
    except OSError as exc:
        raise ThemeError("%s: %s" % (path, exc))
    if len(data) > MAX_THEME_BYTES:
        raise ThemeError("%s: larger than %d bytes" % (path, MAX_THEME_BYTES))
    return data


def _parse(data, path, slug):
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ThemeError("%s: %s" % (path, exc))
    return _build(raw, path, slug)


def _build(raw, path, slug):
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

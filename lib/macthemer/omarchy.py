"""Import a palette published in the Omarchy `colors.toml` format.

Omarchy is another desktop's theme format: one flat `colors.toml` of named
colours, an optional `backgrounds/` folder, and per-application files that
desktop generates for itself from the palette. mac-themer is not Omarchy and
does not read an Omarchy installation: this module reads a *checkout* the
caller fetched, keeps the palette the theme states, and drops every file the
format allows a theme to carry and a mac-themer pack has no use for.

Key resolution follows the published reference, so an imported pack is the
palette the theme's own desktop would show: a canonical name wins over its
legacy alias, a numbered ANSI entry is the fallback for the named colour it
stands for, and anything still missing is derived the way the reference derives
it. Nothing here is a guess about a particular theme.
"""
from __future__ import annotations

import os
import re
import stat
import tomllib
from pathlib import Path

from .palette import PALETTE_KEYS, ThemeError, mix

# A colors.toml is third-party content, so reading one is bounded exactly like
# reading a theme pack.
MAX_COLORS_BYTES = 65536
# How many candidate theme directories one checkout may offer. A repository is
# a theme or a collection, not a filesystem to walk.
MAX_CANDIDATES = 128
# How far below a checkout's root a theme directory may sit: the root itself, a
# theme in a subdirectory, or one `<anything>/<slug>/` level for a collection.
# Anything deeper is not a layout this reader can identify.
MAX_DEPTH = 2
# How many directories one search may look at. A checkout is third-party
# content; nothing here may walk an arbitrary tree.
MAX_WALKED = 4096

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Canonical name -> the spellings that stand in for it, canonical first. Both
# are accepted and canonical wins; this is the pair list the reference
# documents, not a superset. `colorN` is the numbered fallback for the colour it
# stands for and is handled where the ramp is built.
ALIASES = {
    "background": ("background", "bg"),
    "dark_background": ("dark_background", "dark_bg"),
    "darker_background": ("darker_background", "darker_bg"),
    "lighter_background": ("lighter_background", "lighter_bg"),
    "foreground": ("foreground", "fg"),
    "dark_foreground": ("dark_foreground", "dark_fg"),
    "light_foreground": ("light_foreground", "light_fg"),
    "bright_foreground": ("bright_foreground", "bright_fg"),
    "accent": ("accent",),
    "selection": ("selection", "selection_background"),
    "selection_foreground": ("selection_foreground",),
    "muted": ("muted",),
    "cursor": ("cursor",),
}
# `purple` is accepted as a synonym for `magenta`.
BASE_NAMES = ("red", "green", "yellow", "blue", "magenta", "cyan")

# ANSI slot -> the named colour it carries. color0 is the background and color8
# the muted tone, so a theme without a numbered ramp still gets a full one.
ANSI_NAMES = {
    0: "background",
    1: "red",
    2: "green",
    3: "yellow",
    4: "blue",
    5: "magenta",
    6: "cyan",
    7: "foreground",
    8: "muted",
    9: "bright_red",
    10: "bright_green",
    11: "bright_yellow",
    12: "bright_blue",
    13: "bright_magenta",
    14: "bright_cyan",
    15: "bright_foreground",
}

# Semantic roles a pack can pin instead of deriving, and the source colour each
# one comes from. Only pinned when the theme states that colour: a derived tone
# would be this module guessing at a palette it did not choose.
TOKEN_SOURCES = (
    ("surface_container", "lighter_background"),
    ("on_surface_variant", "dark_foreground"),
    ("muted", "muted"),
)

DARK_THRESHOLD = 382


def colors_file(directory):
    return Path(directory) / "colors.toml"


def candidates(checkout):
    """Every directory in *checkout* holding a `colors.toml`, shallowest first.

    A theme repository normally holds one theme at its root. A collection
    states one theme per subdirectory, and that is the only nesting accepted.
    """
    checkout = Path(checkout)
    budget = [MAX_WALKED]
    for depth in range(MAX_DEPTH + 1):
        found = [
            directory
            for directory in _walk(checkout, depth, budget)
            if colors_file(directory).is_file()
        ]
        if found:
            if len(found) > MAX_CANDIDATES:
                raise ThemeError(
                    "%s has more than %d themes" % (checkout, MAX_CANDIDATES))
            return found
    return []


def _walk(root, depth, budget):
    """Directories exactly *depth* levels under *root*, sorted, hidden skipped."""
    if depth == 0:
        yield root
        return
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise ThemeError("%s: %s" % (root, exc))
    for entry in entries:
        budget[0] -= 1
        if budget[0] < 0:
            raise ThemeError("%s has too many directories to search" % root)
        if entry.name.startswith(".") or not entry.is_dir() or entry.is_symlink():
            continue
        yield from _walk(entry, depth - 1, budget)


def read(directory):
    """Read one `colors.toml` from *directory* and resolve it.

    Returns `(resolved, stated)`: every named colour the theme implies, and the
    canonical names it actually wrote down.
    """
    path = colors_file(directory)
    try:
        # O_NONBLOCK keeps a FIFO from blocking; O_NOFOLLOW refuses a symlink
        # that could point outside the checkout.
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError as exc:
        raise ThemeError("%s: %s" % (path, exc))
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ThemeError("%s: not a regular file" % path)
        data = handle.read(MAX_COLORS_BYTES + 1)
    if len(data) > MAX_COLORS_BYTES:
        raise ThemeError("%s: larger than %d bytes" % (path, MAX_COLORS_BYTES))
    try:
        raw = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ThemeError("%s: %s" % (path, exc))
    if not isinstance(raw, dict):
        raise ThemeError("%s: expected a table" % path)
    return resolve(raw, light_marker=(Path(directory) / "light.mode").is_file(),
                   where=path)


def color_table(raw):
    """The entries of a parsed colors.toml that are one `#rrggbb` colour.

    Lower-cased keys. Everything else is dropped rather than guessed at: the
    format also carries Hyprland gradients and mixed-case legacy names, and a
    gradient is not a colour a pack can store.
    """
    colors = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        text = value.strip()
        if HEX.match(text):
            colors[name.strip().lower()] = text.lower()
    return colors


def resolve(raw, light_marker=False, where="colors.toml"):
    """Resolve a parsed `colors.toml` table into every named colour it implies.

    Returns `(resolved, stated)`. `stated` names the canonical colours the
    theme wrote down itself, which is what decides whether a semantic role is
    pinned in the pack or left to mac-themer's own derivation.
    """
    colors = color_table(raw)
    stated = set()

    def pick(*names):
        for name in names:
            if name in colors:
                stated.add(names[0])
                return colors[name]
        return None

    def named(canonical):
        return pick(*ALIASES[canonical])

    background = named("background") or pick("color0")
    foreground = named("foreground") or pick("color7")
    if background is None or foreground is None:
        raise ThemeError(
            "%s: needs background and foreground, or color0 and color7" % where)
    accent = named("accent") or pick("color4") or foreground
    dark_foreground = named("dark_foreground") or pick("color8") or foreground
    muted = named("muted") or pick("color8") or dark_foreground
    light_foreground = named("light_foreground") or pick("color7") or foreground
    bright_foreground = named("bright_foreground") or pick("color15") or foreground
    selection = (named("selection") or pick("color8") or pick("color0") or background)
    selection_foreground = named("selection_foreground") or bright_foreground
    lighter_background = named("lighter_background") or pick("color0") or background
    dark_background = named("dark_background") or mix(background, "#000000", 0.25)
    darker_background = named("darker_background") or mix(background, "#000000", 0.5)

    base = {}
    for index, name in enumerate(BASE_NAMES, start=1):
        spelled = (name, "purple") if name == "magenta" else (name,)
        value = pick(*spelled) or pick("color%d" % index)
        if value is None:
            raise ThemeError("%s: missing %s (color%d)" % (where, name, index))
        base[name] = value
    bright = {}
    for index, name in enumerate(BASE_NAMES, start=9):
        bright[name] = (pick("bright_%s" % name) or pick("color%d" % index)
                        or mix(base[name], "#ffffff", 0.2))

    # A numbered entry wins over the name it stands for: a theme that states
    # both is stating a terminal ramp, and its terminal was already showing the
    # numbered value.
    ramp = {}
    for index in range(16):
        name = ANSI_NAMES[index]
        if name == "background":
            fallback = background
        elif name == "foreground":
            fallback = foreground
        elif name == "muted":
            fallback = muted
        elif name == "bright_foreground":
            fallback = bright_foreground
        elif name.startswith("bright_"):
            fallback = bright[name[len("bright_"):]]
        else:
            fallback = base[name]
        ramp[index] = pick("color%d" % index) or fallback

    resolved = {
        "mode": _mode(raw, background, light_marker),
        "accent": accent,
        "selection": selection,
        "selection_foreground": selection_foreground,
        "muted": muted,
        "background": background,
        "dark_background": dark_background,
        "darker_background": darker_background,
        "lighter_background": lighter_background,
        "foreground": foreground,
        "dark_foreground": dark_foreground,
        "light_foreground": light_foreground,
        "bright_foreground": bright_foreground,
        "cursor": named("cursor") or bright_foreground,
    }
    for index in range(16):
        resolved["color%d" % index] = ramp[index]
    return resolved, frozenset(stated)


def _mode(raw, background, light_marker):
    """Dark or light, in the order the reference decides it."""
    for key in ("mode", "theme_type"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip().lower() in ("dark", "light"):
            return value.strip().lower()
    if light_marker:
        return "light"
    red, green, blue = (int(background[index:index + 2], 16) for index in (1, 3, 5))
    return "light" if red + green + blue > DARK_THRESHOLD else "dark"


def display_name(slug):
    """A readable name for a pack whose repository states none."""
    words = [word for word in re.split(r"[-_.+]+", slug) if word]
    return " ".join(word[:1].upper() + word[1:] for word in words) or slug


def pack(resolved, slug, stated=frozenset(), name=None):
    """One pack document (`themes/<slug>/theme.toml`) as a table.

    The palette is the base16/ANSI layer the source states. The border ring
    leans on the two colours the source already uses for focus and for a raised
    surface, so an imported pack looks like its theme rather than like a
    derivation of it.
    """
    palette = {
        "background": resolved["background"],
        "foreground": resolved["foreground"],
        "cursor": resolved["cursor"],
        "accent": resolved["accent"],
        "selection_background": resolved["selection"],
        "selection_foreground": resolved["selection_foreground"],
    }
    for index in range(16):
        palette["color%d" % index] = resolved["color%d" % index]
    missing = [key for key in PALETTE_KEYS if key not in palette]
    if missing:
        raise ThemeError("%s does not state %s" % (slug, ", ".join(missing)))
    tokens = {
        role: resolved[source]
        for role, source in TOKEN_SOURCES
        if source in stated
    }
    return {
        "name": name or display_name(slug),
        "variant": resolved["mode"],
        "palette": palette,
        "border": {
            "active": resolved["accent"],
            "inactive": resolved["lighter_background"],
        },
        "tokens": tokens,
    }


def document(table, source=None, version=None):
    """Serialize a pack table as the TOML a pack is committed as.

    Written out by hand rather than by a TOML writer: the shape is three fixed
    tables of hex strings, and an imported pack should read exactly like the
    hand-written ones beside it.
    """
    origin = (" — imported from %s by mac-themer %s." % (source, version)).rstrip() \
        if source else ""
    lines = [
        "# %s%s" % (table["name"], origin),
        "#",
        "# One file per pack. Every colour below came from the theme's own",
        "# colors.toml; the semantic roles this pack does not pin are derived by",
        "# lib/macthemer/tokens.py.",
        "",
        "name = %s" % _string(table["name"]),
        "variant = %s" % _string(table["variant"]),
        "",
        "[palette]",
    ]
    for key in PALETTE_KEYS:
        lines.append("%s = %s" % (key, _string(table["palette"][key])))
    lines += ["", "[border]"]
    for key in ("active", "inactive"):
        lines.append("%s = %s" % (key, _string(table["border"][key])))
    if table["tokens"]:
        lines += ["", "[tokens]"]
        for key in sorted(table["tokens"]):
            lines.append("%s = %s" % (key, _string(table["tokens"][key])))
    return "\n".join(lines) + "\n"


def _string(value):
    if not isinstance(value, str) or not value:
        raise ThemeError("refusing to serialize %r" % (value,))
    if any(character in value for character in '"\\\n\r\x00'):
        raise ThemeError("refusing to serialize %r" % (value,))
    return '"%s"' % value

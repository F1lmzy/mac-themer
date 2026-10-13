"""Renderers: one palette in, every consumer's format out.

Each renderer is a pure function of a resolved pack. That is what makes the
generated files testable — same input, byte-identical output, checked by
tests/test_render.py against committed goldens.
"""
from __future__ import annotations

import json

from . import __version__
from .palette import alpha_byte, argb

GENERATED = "Generated from themes/%s/theme.toml by mac-themer %s. Do not edit."

# The five non-palette Ghostty options the pack carries, in Ghostty's own
# spelling, mapped to their palette key.
GHOSTTY_SCALARS = (
    ("background", "background"),
    ("foreground", "foreground"),
    ("cursor-color", "cursor"),
    ("selection-background", "selection_background"),
    ("selection-foreground", "selection_foreground"),
)

BAR_EXPORTS = (
    ("BAR_BG_SOLID", "background_solid", 1.0),
    ("ITEM_BG", "item_bg", 1.0),
    ("ACCENT", "accent", 1.0),
    ("LABEL_COLOR", "label", 1.0),
    ("ICON_COLOR", "icon", 1.0),
    ("MUTED", "muted", 1.0),
    ("RED", "red", 1.0),
    ("GREEN", "green", 1.0),
    ("YELLOW", "yellow", 1.0),
)


def ghostty(theme):
    lines = ["# " + GENERATED % (theme.slug, __version__)]
    for option, key in GHOSTTY_SCALARS:
        lines.append("%s = %s" % (option, theme.palette[key]))
    for index in range(16):
        lines.append("palette = %d=%s" % (index, theme.palette["color%d" % index]))
    return "\n".join(lines) + "\n"


def colors_toml(theme):
    """The base16/ANSI layer on its own, for tools that only want the palette."""
    lines = ["# " + GENERATED % (theme.slug, __version__), ""]
    for key in ("accent", "cursor", "foreground", "background",
                "selection_foreground", "selection_background"):
        lines.append('%s = "%s"' % (key, theme.palette[key]))
    lines.append("")
    for index in range(16):
        lines.append('color%d = "%s"' % (index, theme.palette["color%d" % index]))
    return "\n".join(lines) + "\n"


def sketchybar_sh(theme, tokens, bar):
    alpha = float(theme.bar.get("background_alpha", 0.902))
    lines = [
        "#!/usr/bin/env bash",
        "# %s - bar palette (0xAARRGGBB)" % theme.name,
        "export BAR_COLOR=0x%08x" % argb(bar["background"], alpha),
    ]
    for name, key, opacity in BAR_EXPORTS:
        lines.append("export %s=0x%08x" % (name, argb(bar[key], opacity)))
    return "\n".join(lines) + "\n"


def borders_sh(theme):
    return "\n".join([
        "#!/usr/bin/env bash",
        "# %s - border palette (0xAARRGGBB)" % theme.name,
        "export ACTIVE_COLOR=0x%08x" % argb(theme.border["active"]),
        "export INACTIVE_COLOR=0x%08x" % argb(theme.border["inactive"]),
        "",
    ])


def resolved(theme, tokens, bar):
    """The machine-readable palette every app-facing consumer should read.

    The shell fragments exist for consumers already wired to the omarchy
    convention. New consumers get this file instead: it carries the palette,
    the semantic roles and the named border and bar colours in one place, so
    an app needs no theme logic of its own and no shell parsing. maccer and
    the Qt pill are the intended readers.
    """
    return {
        "schema": 1,
        "generated_by": "mac-themer %s" % __version__,
        "slug": theme.slug,
        "name": theme.name,
        "variant": theme.variant,
        # Relative to the repo on purpose: a resolved palette is a published
        # artifact and consumers read it from the state directory, so it must
        # not carry this machine's paths.
        "pack": "themes/%s" % theme.slug,
        "backgrounds": "themes/%s/backgrounds" % theme.slug,
        "alpha_byte": alpha_byte(theme.bar.get("background_alpha", 0.902)),
        "palette": {key: theme.palette[key] for key in sorted(theme.palette)},
        "tokens": {key: tokens[key] for key in sorted(tokens)},
        "border": {"active": theme.border["active"], "inactive": theme.border["inactive"]},
        "bar": {key: bar[key] for key in sorted(bar)},
    }


def resolved_json(theme, tokens, bar):
    return json.dumps(resolved(theme, tokens, bar), indent=2, sort_keys=False) + "\n"


def artifacts(theme, tokens, bar):
    """Everything a pack render produces, keyed by path relative to the pack."""
    return {
        "colors.toml": colors_toml(theme),
        "ghostty.conf": ghostty(theme),
        "sketchybar.sh": sketchybar_sh(theme, tokens, bar),
        "borders.sh": borders_sh(theme),
    }

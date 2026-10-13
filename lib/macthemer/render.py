"""Renderers: one palette in, every consumer's format out.

Each renderer is a pure function of a resolved pack. That is what makes the
generated files testable — same input, byte-identical output, checked by
tests/test_render.py against committed goldens.

There are deliberately few output formats. The palette reaches anything with a
UI through current.json, which is written atomically and needs no shell
parsing; the two files here exist for consumers that read a config file rather
than a palette.
"""
from __future__ import annotations

import json

from . import __version__
from .palette import alpha_byte

GENERATED = "Generated from themes/%s/theme.toml by mac-themer %s. Do not edit."

# The five non-palette Ghostty options the pack carries, in Ghostty's own
# spelling, mapped to their palette key. Hyphenated, not underscored: Ghostty
# accepts both, but this is the spelling its documentation uses and the one the
# previous setup wrote, and a config that warns is not a cosmetic difference.
GHOSTTY_SCALARS = (
    ("background", "background"),
    ("foreground", "foreground"),
    ("cursor-color", "cursor"),
    ("selection-background", "selection_background"),
    ("selection-foreground", "selection_foreground"),
)


def ghostty(theme):
    lines = ["# " + GENERATED % (theme.slug, __version__)]
    for option, key in GHOSTTY_SCALARS:
        lines.append("%s = %s" % (option, theme.palette[key]))
    for index in range(16):
        lines.append("palette = %d=%s" % (index, theme.palette["color%d" % index]))
    return "\n".join(lines) + "\n"


def colors_toml(theme):
    """The base16/ANSI layer on its own.

    A pack carries it so anything that only wants a terminal palette can read
    one file instead of learning current.json, and so the pack is legible to a
    human without the tool.
    """
    lines = ["# " + GENERATED % (theme.slug, __version__), ""]
    for key in ("accent", "cursor", "foreground", "background",
                "selection_foreground", "selection_background"):
        lines.append('%s = "%s"' % (key, theme.palette[key]))
    lines.append("")
    for index in range(16):
        lines.append('color%d = "%s"' % (index, theme.palette["color%d" % index]))
    return "\n".join(lines) + "\n"


def resolved(theme, tokens, bar):
    """The machine-readable palette every app-facing consumer reads.

    This is the interface. It carries the palette, the semantic roles and the
    named border and bar colours in one place, so an app needs no theme logic
    of its own and no shell parsing: point a file watcher at it and repaint.
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
    }

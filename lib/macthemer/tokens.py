"""The semantic layer: one palette, named roles every consumer can read.

A pack states a base16/ANSI palette plus explicit border colours. Terminals
need exactly that. Anything with a UI needs roles instead — surface, on-surface,
primary, outline — so the roles are derived here, once, and every renderer
works from the result. A pack may pin any role in its own [tokens] table when
the derived value is the wrong judgement call, which is how the elevation step
and the muted tone stay exactly as they were hand-tuned.
"""
from __future__ import annotations

from .palette import mix

TOKEN_ORDER = (
    "surface",
    "surface_container_low",
    "surface_container",
    "surface_container_high",
    "surface_container_highest",
    "on_surface",
    "on_surface_variant",
    "outline",
    "outline_variant",
    "primary",
    "on_primary",
    "primary_container",
    "on_primary_container",
    "secondary",
    "info",
    "success",
    "warning",
    "error",
    "muted",
)

# Elevation steps between the pack's background and foreground. One ramp for
# every palette, so a new pack needs no hand-picked greys.
ELEVATION = {
    "surface_container_low": 0.06,
    "surface_container": 0.11,
    "surface_container_high": 0.16,
    "surface_container_highest": 0.26,
    "on_surface_variant": 0.72,
    "outline_variant": 0.22,
    "outline": 0.40,
    "muted": 0.42,
}


def tokens_for(theme):
    background = theme.palette["background"]
    foreground = theme.palette["foreground"]
    palette = theme.palette
    tokens = {
        "surface": background,
        "on_surface": foreground,
        "primary": palette["accent"],
        "on_primary": background,
        "primary_container": palette["accent"],
        "on_primary_container": background,
        "secondary": palette["color6"],
        "info": palette["color4"],
        "success": palette["color2"],
        "warning": palette["color3"],
        "error": palette["color1"],
    }
    for role, step in ELEVATION.items():
        tokens[role] = mix(background, foreground, step)
    tokens.update(theme.token_overrides)
    return {role: tokens[role] for role in TOKEN_ORDER}


def bar_for(theme, tokens):
    """The bar's own vocabulary, filled from the tokens.

    Semantic colours come from the *bright* ANSI ramp: a bar is small, sits
    against the wallpaper and is read at a glance, and the normal ramp is
    tuned for text on the terminal background instead. A pack can override
    any of them.
    """
    bar = {
        "background": tokens["surface"],
        "background_solid": tokens["surface"],
        "item_bg": tokens["surface_container"],
        "accent": tokens["primary"],
        "label": tokens["on_surface"],
        "icon": tokens["on_surface"],
        "muted": tokens["muted"],
        "red": theme.palette["color9"],
        "green": theme.palette["color10"],
        "yellow": theme.palette["color11"],
    }
    bar.update({k: v for k, v in theme.bar.items() if k != "background_alpha"})
    return bar


def background_alpha(theme):
    return float(theme.bar.get("background_alpha", 0.902))

"""The fan-out: what actually happens when a theme is applied.

Side effects are collected as human-readable strings and returned, so both
the CLI and the tests can see exactly what a run did without re-deriving it.
Nothing here prints.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import palette as palette_mod, paths, render, tokens as tokens_mod

# Korren keeps hand-tuned built-ins under these names and live-derives from
# the palette for anything else. It watches its config, so this repaints.
KORREN_BUILTINS = ("tokyo-night", "catppuccin", "gruvbox", "solarized-dark",
                   "osaka-jade", "daylight")

WALLPAPER_SCRIPT = """on run argv
  tell application "System Events" to tell every desktop to set picture to (item 1 of argv)
end run"""

GHOSTTY_RELOAD = """tell application "Ghostty"
  if (count of terminals) > 0 then
    perform action "reload_config" on first terminal
  end if
end tell"""

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff")


def dry_run():
    """MACTHEMER_DRY_RUN=1 renders and records, but changes nothing outside
    the state directory. The integration tests apply real packs end to end;
    without this they would take over the tester's wallpaper, their Ghostty
    window and Korren's config to prove a symlink moved."""
    return os.environ.get("MACTHEMER_DRY_RUN") == "1"


def write_atomic(path, text):
    """Write through a temp file: readers watch these paths and never lock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, path)


def write_if_changed(path, text):
    path = Path(path)
    if path.is_file() and path.read_text() == text:
        return False
    write_atomic(path, text)
    return True


def relink(path, target):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() and os.readlink(path) == str(target):
        return False
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            raise RuntimeError("refusing to replace directory %s with a symlink" % path)
        path.unlink()
    path.symlink_to(target)
    return True


def backgrounds(theme):
    folder = theme.source.parent / "backgrounds"
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir()
                  if path.suffix.lower() in IMAGE_SUFFIXES)


def set_wallpaper(path):
    """Prefer the omacosy helper when it is installed, for its NSWorkspace path.

    It is the only implementation on this machine known to survive macOS 14+
    reliably, where System Events wallpaper scripting returns missing value on
    some desktops. The osascript below is the fallback and stays
    argument-based: a filename out of a theme pack is third-party content and
    must never be spliced into script text.
    """
    helper = paths.bin_dir() / "omacosy-helper"
    if dry_run():
        return "wallpaper (dry run)"
    if helper.is_file() and os.access(helper, os.X_OK):
        result = subprocess.run([str(helper), "wallpaper", str(path)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return "wallpaper via omacosy-helper"
    subprocess.run(["osascript", "-", str(path)], input=WALLPAPER_SCRIPT,
                   capture_output=True, text=True)
    return "wallpaper via osascript"


def remember_background(path):
    """Record the choice where both this tool and the legacy helper look.

    The omacosy state link is written so an installed omacosy-helper can still
    resync a display that was unplugged during a theme change.
    """
    for link in (paths.run_dir() / "background", paths.legacy_run_dir() / "background"):
        try:
            relink(link, path)
        except OSError:
            pass


def korren(name):
    """Point Korren at the palette, if Korren is installed."""
    config = paths.home() / "Library" / "Application Support" / "korren" / "config.toml"
    if dry_run() or not config.is_file():
        return None
    wanted = name if name in KORREN_BUILTINS else "omarchy"
    lines = config.read_text().splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("name = "):
            lines[index] = 'name = "%s"\n' % wanted
            break
    else:
        return None
    write_if_changed(config, "".join(lines))
    return "korren theme %s" % wanted


def reload_ghostty():
    if dry_run():
        return None
    if subprocess.run(["pgrep", "-x", "ghostty"], capture_output=True).returncode != 0:
        return None
    result = subprocess.run(["osascript", "-e", GHOSTTY_RELOAD], capture_output=True, text=True)
    return "ghostty reloaded" if result.returncode == 0 else "ghostty reload failed (reload manually)"


def render_pack(theme):
    """Write the generated files into the pack itself.

    They live beside theme.toml rather than in the state directory because
    the omarchy-convention pointer is a symlink to the pack directory: a
    consumer that resolves that symlink and reads sketchybar.sh, or walks
    upwards for backgrounds, has to find both there. Names are gitignored.
    """
    tokens = tokens_mod.tokens_for(theme)
    bar = tokens_mod.bar_for(theme, tokens)
    written = []
    for name, text in render.artifacts(theme, tokens, bar).items():
        if write_if_changed(theme.source.parent / name, text):
            written.append(name)
    return tokens, bar, written


def apply(theme, wallpaper=True, korren_flag=True, reload=True, index=0):
    """Apply a pack and report every side effect, in the order it happened."""
    actions = []
    tokens, bar, written = render_pack(theme)
    if written:
        actions.append("rendered %s" % ", ".join(written))

    if write_if_changed(paths.resolved_file(), render.resolved_json(theme, tokens, bar)):
        actions.append("wrote %s" % paths.resolved_file())
    if relink(paths.current_link(), theme.source.parent):
        actions.append("current -> %s" % theme.slug)

    # The omarchy convention, kept as a real directory of generated files so
    # consumers wired to it need no changes while the machine migrates.
    compat = paths.compat_dir()
    if relink(compat / "theme", theme.source.parent):
        actions.append("compat theme -> %s" % theme.slug)
    if write_if_changed(compat / "ghostty.conf", render.ghostty(theme)):
        actions.append("compat ghostty.conf")

    pictures = backgrounds(theme)
    if wallpaper and pictures:
        chosen = pictures[min(index, len(pictures) - 1)]
        remember_background(chosen)
        actions.append(set_wallpaper(chosen) + " (%s)" % chosen.name)
    if korren_flag:
        result = korren(theme.slug)
        if result:
            actions.append(result)
    if reload:
        result = reload_ghostty()
        if result:
            actions.append(result)
    return actions

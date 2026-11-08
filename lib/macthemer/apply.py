"""The fan-out: what actually happens when a theme is applied.

Every path this touches belongs to mac-themer. Nothing here looks for another
project's helper, reads another project's directory, or writes into one: the
themer installs, runs and uninstalls on its own.

Side effects are collected as human-readable strings and returned, so both the
CLI and the tests can see exactly what a run did without re-deriving it.
Nothing here prints.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import paths, render
from . import tokens as tokens_mod
from .palette import ThemeError

# Korren keeps hand-tuned built-ins under these names and live-derives from the
# palette for anything else. It watches its config, so this repaints.
KORREN_BUILTINS = ("tokyo-night", "catppuccin", "gruvbox", "solarized-dark",
                   "osaka-jade", "daylight")

WALLPAPER_HELPER = "macthemer-wallpaper"

# Fallback for a machine that has not built the helper yet. System Events
# wallpaper scripting is unreliable on macOS 14+, which is why the helper
# exists, but it costs nothing to try and keeps `mac-themer set` working from a
# bare checkout. The path is an ARGUMENT, never spliced into script text: a
# filename out of a theme pack is third-party content.
WALLPAPER_SCRIPT = """on run argv
  tell application "System Events" to tell every desktop to set picture to (item 1 of argv)
end run"""

GHOSTTY_RELOAD = """tell application "Ghostty"
  if (count of terminals) > 0 then
    perform action "reload_config" on first terminal
  end if
end tell"""

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".tiff")

# A wallpaper identity crosses a process boundary and comes back as an
# argument, so it is bounded and must not be able to name another directory.
MAX_WALLPAPER_ID = 128


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
    """The pack's background images, sorted by filename.

    Hidden entries are skipped: `.DS_Store` is not a wallpaper, and a dot-name
    is not something the catalog should publish.
    """
    folder = theme.source.parent / "backgrounds"
    if not folder.is_dir():
        return []
    return sorted(path for path in folder.iterdir()
                  if not path.name.startswith(".")
                  and path.suffix.lower() in IMAGE_SUFFIXES)


def wallpaper_ids(theme):
    """The pack's wallpapers as path-free identities, in apply order.

    A wallpaper's identity is its filename: `catalog` publishes it and `apply
    --background` takes it back. A name that could address another directory is
    refused rather than rewritten, because the catalog entry is part of what
    authorizes the later write.
    """
    ids = []
    for path in backgrounds(theme):
        name = path.name
        if (len(name.encode("utf-8")) > MAX_WALLPAPER_ID
                or name in (".", "..")
                or "/" in name or "\\" in name or "\x00" in name
                or any(character < " " or character == "\x7f" for character in name)):
            raise ThemeError(
                "themes/%s/backgrounds: %r cannot be published as a wallpaper"
                % (theme.slug, name))
        ids.append(name)
    return ids


def wallpaper_path(theme, ident):
    """Resolve a published wallpaper identity back to its file, or None."""
    for path in backgrounds(theme):
        if path.name == ident:
            return path
    return None


def wallpaper_helper():
    candidate = paths.bin_dir() / WALLPAPER_HELPER
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def set_wallpaper(path):
    """Set the desktop picture and report how, or None if every route failed."""
    if dry_run():
        return "wallpaper (dry run)"
    helper = wallpaper_helper()
    if helper is not None:
        result = subprocess.run([str(helper), "set", str(path)],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return "wallpaper via %s" % WALLPAPER_HELPER
    result = subprocess.run(["osascript", "-", str(path)], input=WALLPAPER_SCRIPT,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return "wallpaper via osascript"


def resync_wallpaper():
    """Re-assert the remembered picture.

    macOS keeps the desktop picture per display, so a screen that was unplugged
    during a theme change comes back showing the theme before it.
    """
    link = paths.backgrounds_link()
    if dry_run() or not link.is_symlink():
        return None
    target = Path(os.readlink(link))
    if not target.is_file():
        return None
    helper = wallpaper_helper()
    if helper is None:
        return None
    result = subprocess.run([str(helper), "resync", str(target)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def remember_background(path):
    # Recorded even in a dry run: this link lives in mac-themer's own state
    # directory, which is the sandbox during tests, and the background cycle
    # reads it to know where it is. Only the desktop-touching effects are
    # suppressed.
    try:
        relink(paths.backgrounds_link(), path)
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

    They live beside theme.toml rather than in the state directory because the
    active-theme pointer is a symlink to the pack directory, so a consumer that
    resolves it and walks upwards for backgrounds, or reads the pack's palette,
    finds both there. The names are gitignored.
    """
    tokens = tokens_mod.tokens_for(theme)
    bar = tokens_mod.bar_for(theme, tokens)
    written = []
    for name, text in render.artifacts(theme, tokens, bar).items():
        if write_if_changed(theme.source.parent / name, text):
            written.append(name)
    return tokens, bar, written


def apply(theme, wallpaper=True, korren_flag=True, reload=True, index=0, background=None):
    """Apply a pack and report every side effect, in the order it happened.

    `background` names one of the pack's own images and wins over `index`; a
    file that is not part of the pack is refused instead of set.
    """
    actions = []
    tokens, bar, written = render_pack(theme)
    if written:
        actions.append("rendered %s" % ", ".join(written))

    if write_if_changed(paths.resolved_file(), render.resolved_json(theme, tokens, bar)):
        actions.append("wrote current.json")
    # Ghostty is told to load this exact path from the user's config, so a
    # theme switch never rewrites that config.
    if write_if_changed(paths.ghostty_fragment(), render.ghostty(theme)):
        actions.append("wrote ghostty.conf")
    if relink(paths.current_link(), theme.source.parent):
        actions.append("current -> %s" % theme.slug)

    pictures = backgrounds(theme)
    if background is not None and background not in pictures:
        raise RuntimeError("%s is not a background of %s" % (background.name, theme.slug))
    if wallpaper and pictures:
        chosen = background if background is not None else pictures[min(index, len(pictures) - 1)]
        remember_background(chosen)
        outcome = set_wallpaper(chosen)
        actions.append((outcome or "wallpaper failed") + " (%s)" % chosen.name)
    if korren_flag:
        result = korren(theme.slug)
        if result:
            actions.append(result)
    if reload:
        result = reload_ghostty()
        if result:
            actions.append(result)
    return actions

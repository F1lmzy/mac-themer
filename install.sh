#!/usr/bin/env bash
# mac-themer install — build the border ring and the wallpaper helper, put the
# CLI on PATH, and apply a theme if none is applied yet.
#
# Idempotent: re-running rebuilds only what changed. Everything it creates is
# under ~/.local, ~/.config/macthemer or ~/Library/LaunchAgents, and
# uninstall.sh reverses it. Nothing here looks for, reads or writes another
# project's files, so mac-themer installs and uninstalls on its own.
set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m==>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m==>\033[0m %s\n' "$*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
STATE_DIR="${MACTHEMER_STATE:-$HOME/.config/macthemer}"
BIN_DIR="${MACTHEMER_BIN:-$HOME/.local/bin}"
AGENTS_DIR="${MACTHEMER_AGENTS:-$HOME/Library/LaunchAgents}"
UID_N="$(id -u)"
PLIST="$AGENTS_DIR/com.macthemer.borders.plist"
RING="$BIN_DIR/macthemer-borders"
WALLPAPER="$BIN_DIR/macthemer-wallpaper"

command -v swiftc >/dev/null || die "swiftc not found — install the Xcode command line tools"
command -v python3 >/dev/null || die "python3 not found"
python3 - <<'PY' || die "mac-themer needs python3 3.11 or newer (tomllib)"
import sys
sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY

# --- 1. state ---------------------------------------------------------------

mkdir -p "$STATE_DIR" "$BIN_DIR" "$AGENTS_DIR"
if [ ! -f "$STATE_DIR/borders.conf" ]; then
  cp "$REPO_DIR/borders/borders.conf" "$STATE_DIR/borders.conf"
  say "seeded $STATE_DIR/borders.conf"
fi

# --- 2. the CLI on PATH -----------------------------------------------------

# theme-set/theme-next/theme-bg-next keep their names because chords and
# keybindings already call them; mac-themer is the one to learn.
link() {
  local target="$1" name="$2"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$name" ]; then return 0; fi
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    warn "$target is a real file, not ours; moving it to $target.saved"
    mv "$target" "$target.saved"
  fi
  ln -sfn "$name" "$target"
  say "linked $target -> $name"
}
link "$BIN_DIR/mac-themer" "$REPO_DIR/bin/mac-themer"
link "$BIN_DIR/theme-set" "$REPO_DIR/bin/theme-set"
link "$BIN_DIR/theme-next" "$REPO_DIR/bin/theme-next"
link "$BIN_DIR/theme-bg-next" "$REPO_DIR/bin/theme-bg-next"

# --- 3. the two binaries ----------------------------------------------------

build() {
  local output="$1" source="$2"; shift 2
  if [ ! -x "$output" ] || [ "$source" -nt "$output" ]; then
    say "building $(basename "$output")"
    swiftc -O "$@" -o "$output" "$source"
  fi
}
build "$RING" "$REPO_DIR/borders/borders.swift" \
  -F /System/Library/PrivateFrameworks -framework SkyLight
build "$WALLPAPER" "$REPO_DIR/helper/wallpaper.swift" -framework AppKit

# --- 4. the ring agent ------------------------------------------------------

sed "s|__BINARY__|$RING|" "$REPO_DIR/borders/com.macthemer.borders.plist.template" > "$PLIST"
launchctl bootout "gui/$UID_N/com.macthemer.borders" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST" 2>/dev/null \
  || die "could not load $PLIST"
say "border ring loaded from $PLIST"

# A second ring daemon draws a second ring. mac-themer does not manage other
# projects' agents, so it reports the conflict instead of taking it over.
others="$(launchctl list 2>/dev/null | awk '$3 ~ /[Bb]orders/ && $3 != "com.macthemer.borders" { print $3 }' || true)"
if [ -n "$others" ]; then
  warn "another border daemon is loaded: $others"
  warn "two agents will draw two rings — stop it, or mac-themer doctor will keep saying so."
fi

# --- 5. a theme, if none is applied yet -------------------------------------

if [ ! -e "$STATE_DIR/current" ]; then
  say "applying the first pack (tokyo-night)"
  "$REPO_DIR/bin/mac-themer" set tokyo-night
fi

say "done. 'mac-themer list' for packs, 'mac-themer doctor' to audit."
say "Ghostty follows the palette through: config-file = $STATE_DIR/ghostty.conf"

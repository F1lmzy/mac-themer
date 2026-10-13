#!/usr/bin/env bash
# mac-themer uninstall — remove the ring, the binaries and the symlinks.
#
# Leaves theme packs, your borders.conf and the state directory alone: those
# are yours. Pass --purge-state to delete the state directory as well.
#
# It gives nothing back to another project, because install.sh never took
# anything from one.
set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
STATE_DIR="${MACTHEMER_STATE:-$HOME/.config/macthemer}"
BIN_DIR="${MACTHEMER_BIN:-$HOME/.local/bin}"
AGENTS_DIR="${MACTHEMER_AGENTS:-$HOME/Library/LaunchAgents}"
UID_N="$(id -u)"
PLIST="$AGENTS_DIR/com.macthemer.borders.plist"
PURGE=0
[ "${1:-}" = "--purge-state" ] && PURGE=1

# --- the ring ---------------------------------------------------------------

launchctl bootout "gui/$UID_N/com.macthemer.borders" 2>/dev/null || true
if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  say "removed $PLIST"
fi

# --- the binaries and the symlinks ------------------------------------------

for binary in macthemer-borders macthemer-wallpaper; do
  if [ -e "$BIN_DIR/$binary" ]; then
    rm -f "$BIN_DIR/$binary"
    say "removed $BIN_DIR/$binary"
  fi
done

# Only links that point into this checkout are removed, and a real file at one
# of these names is left alone: it is somebody else's install.
for name in mac-themer theme-set theme-next theme-bg-next; do
  path="$BIN_DIR/$name"
  if [ -L "$path" ]; then
    case "$(readlink "$path")" in
      "$REPO_DIR"/*)
        rm -f "$path"
        say "unlinked $path"
        ;;
    esac
  fi
done

if [ "$PURGE" = 1 ]; then
  rm -rf "$STATE_DIR"
  say "removed $STATE_DIR"
else
  say "kept $STATE_DIR (borders.conf, current theme, current.json)"
fi
say "Ghostty will warn about a missing $STATE_DIR/ghostty.conf until its config-file line is removed"

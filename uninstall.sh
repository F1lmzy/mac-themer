#!/usr/bin/env bash
# mac-themer uninstall — remove the border ring and the symlinks.
#
# Leaves theme packs, your borders.conf and the state directory alone: those
# are yours. Pass --purge-state to delete the state directory as well.
set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
STATE_DIR="${MACTHEMER_STATE:-$HOME/.config/macthemer}"
BIN_DIR="${MACTHEMER_BIN:-$HOME/.local/bin}"
AGENTS_DIR="${MACTHEMER_AGENTS:-$HOME/Library/LaunchAgents}"
UID_N="$(id -u)"
PLIST="$AGENTS_DIR/com.macthemer.borders.plist"
DISABLED_RECORD="$STATE_DIR/disabled-agents"
PURGE=0
[ "${1:-}" = "--purge-state" ] && PURGE=1

# --- the ring ---------------------------------------------------------------

launchctl bootout "gui/$UID_N/com.macthemer.borders" 2>/dev/null || true
if [ -f "$PLIST" ]; then
  rm -f "$PLIST"
  say "removed $PLIST"
fi
if [ -x "$BIN_DIR/macthemer-borders" ]; then
  rm -f "$BIN_DIR/macthemer-borders"
  say "removed $BIN_DIR/macthemer-borders"
fi

# --- symlinks, but only the ones that point at us ---------------------------

# Only links that point into this checkout are removed, and a real file at
# one of these names is left alone: it is somebody else's install.
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

# --- give back whatever install.sh took over --------------------------------

if [ -f "$DISABLED_RECORD" ] && grep -qx 'com.omacosy.borders' "$DISABLED_RECORD"; then
  legacy="$AGENTS_DIR/com.omacosy.borders.plist"
  if [ -f "$legacy" ]; then
    launchctl enable "gui/$UID_N/com.omacosy.borders" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_N" "$legacy" 2>/dev/null || true
    say "com.omacosy.borders handed back"
  else
    say "com.omacosy.borders was disabled by install.sh but its plist is gone"
  fi
  rm -f "$DISABLED_RECORD"
fi

if [ "$PURGE" = 1 ]; then
  rm -rf "$STATE_DIR"
  say "removed $STATE_DIR"
else
  say "kept $STATE_DIR (borders.conf, current theme, disabled-agents record)"
fi

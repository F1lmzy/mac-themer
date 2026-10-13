#!/usr/bin/env bash
# mac-themer install — build the border ring and put the CLI on PATH.
#
# Idempotent: re-running rebuilds only what changed. Every step that changes
# something outside this repo prints what it did, and uninstall.sh reverses it.
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
BINARY="$BIN_DIR/macthemer-borders"
DISABLED_RECORD="$STATE_DIR/disabled-agents"

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

# theme-set/theme-next/theme-bg-next keep their names because existing chords
# and apps already call them; mac-themer is the one to learn.
link() {
  local target="$1" name="$2"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$name" ]; then return 0; fi
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    warn "$target is a real file (not ours); moving to $target.macthemer-saved"
    mv "$target" "$target.macthemer-saved"
  fi
  ln -sfn "$name" "$target"
  say "linked $target -> $name"
}
link "$BIN_DIR/mac-themer" "$REPO_DIR/bin/mac-themer"
link "$BIN_DIR/theme-set" "$REPO_DIR/bin/theme-set"
link "$BIN_DIR/theme-next" "$REPO_DIR/bin/theme-next"
link "$BIN_DIR/theme-bg-next" "$REPO_DIR/bin/theme-bg-next"

# --- 3. the border ring -----------------------------------------------------

if [ ! -x "$BINARY" ] || [ "$REPO_DIR/borders/borders.swift" -nt "$BINARY" ]; then
  say "building macthemer-borders"
  swiftc -O -F /System/Library/PrivateFrameworks -framework SkyLight \
    -o "$BINARY" "$REPO_DIR/borders/borders.swift"
fi

# A second ring daemon would draw a second ring. Hand the job over rather
# than let both run: record what was stopped so uninstall.sh can give it back.
if launchctl print "gui/$UID_N/com.omacosy.borders" >/dev/null 2>&1; then
  say "stopping com.omacosy.borders so it does not draw a second ring"
  launchctl bootout "gui/$UID_N/com.omacosy.borders" 2>/dev/null || true
  launchctl disable "gui/$UID_N/com.omacosy.borders" 2>/dev/null || true
  printf 'com.omacosy.borders\n' >> "$DISABLED_RECORD"
fi

sed "s|__BINARY__|$BINARY|" "$REPO_DIR/borders/com.macthemer.borders.plist.template" > "$PLIST"
launchctl bootout "gui/$UID_N/com.macthemer.borders" 2>/dev/null || true
launchctl bootstrap "gui/$UID_N" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST" 2>/dev/null \
  || die "could not load $PLIST"
say "border ring loaded from $PLIST"

# --- 4. a theme, if none is applied yet -------------------------------------

if [ ! -e "$STATE_DIR/current" ]; then
  say "applying the first pack (tokyo-night)"
  "$REPO_DIR/bin/mac-themer" set tokyo-night
fi

say "done. 'mac-themer list' to see packs, 'mac-themer doctor' to audit."
say "if another borders daemon is set up to start at login, remove it too — doctor reports it."

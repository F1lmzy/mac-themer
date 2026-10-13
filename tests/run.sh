#!/usr/bin/env bash
# mac-themer test suite.
#
# Nothing here touches the real desktop. The unit and golden tests read the
# checkout; the CLI tests run against a copy of it with MACTHEMER_* pointed at
# a temporary tree and MACTHEMER_DRY_RUN=1, so "set a theme" moves a symlink in
# /tmp instead of the tester's wallpaper, Ghostty window and Korren config.
#
#   tests/run.sh                  unit, golden, CLI
#   MACTHEMER_TEST_BUILD=1 tests/run.sh   also compile borders.swift (slow)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

step() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ok\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mFAIL\033[0m %s\n' "$*" >&2; exit 1; }

step "syntax"
for file in "$REPO_DIR/install.sh" "$REPO_DIR/uninstall.sh" "$REPO_DIR"/bin/* "$REPO_DIR/tests"/*.sh; do
  # bin/ holds one python entry point among the shell wrappers; check those too,
  # just with the other parser below.
  head -1 "$file" | grep -q bash || continue
  bash -n "$file" || fail "bash -n $file"
done
python3 - "$REPO_DIR" <<'PY' || fail "python syntax"
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])
for path in list((root / "lib").rglob("*.py")) + [root / "bin" / "mac-themer"] + list((root / "tests").glob("*.py")):
    ast.parse(path.read_text())
PY
ok "bash and python parse"

step "unit, golden and regression pins"
MACTHEMER_REPO="$REPO_DIR" PYTHONPATH="$REPO_DIR/lib" \
  python3 -m unittest discover -s "$REPO_DIR/tests" -t "$REPO_DIR/tests" -p 'test_*.py'

step "rendering into a throwaway checkout"
sandbox="$TMP/repo"
cp -R "$REPO_DIR" "$sandbox"
rm -rf "$sandbox/.git"
# 15 MB of wallpapers are not worth copying; two stub images per pack keep the
# cycle test honest without them.
find "$sandbox/themes" -maxdepth 2 -name backgrounds -type d -exec rm -rf {} +
for pack in "$sandbox"/themes/*/; do
  mkdir -p "$pack/backgrounds"
  printf 'stub' > "$pack/backgrounds/0-one.png"
  printf 'stub' > "$pack/backgrounds/1-two.png"
done

export MACTHEMER_REPO="$sandbox" \
       MACTHEMER_STATE="$TMP/state" \
       MACTHEMER_RUN="$TMP/run" \
       MACTHEMER_HOME="$TMP/home" \
       MACTHEMER_BIN="$TMP/bin" \
       MACTHEMER_AGENTS="$TMP/agents" \
       MACTHEMER_DRY_RUN=1

cli="$sandbox/bin/mac-themer"

[ "$("$cli" current)" = "none" ] || fail "a fresh tree already has a current theme"
"$cli" set catppuccin >/dev/null
[ "$("$cli" current)" = "catppuccin" ] || fail "set did not take effect"
[ -f "$TMP/state/current.json" ] || fail "no resolved palette was written"
ok "set applies a pack"

python3 - "$TMP/state/current.json" <<'PY' || fail "resolved palette is not what it should be"
import json, sys
resolved = json.load(open(sys.argv[1]))
assert resolved["slug"] == "catppuccin", resolved["slug"]
assert resolved["border"]["active"] == "#cba6f7", resolved["border"]
assert resolved["alpha_byte"] == 230, resolved["alpha_byte"]
assert resolved["tokens"]["primary"] == "#cba6f7", resolved["tokens"]["primary"]
assert len(resolved["palette"]) == 22, len(resolved["palette"])
PY
ok "resolved palette carries border, tokens and the palette"

[ -L "$TMP/state/current" ] || fail "no current symlink"
[ -f "$TMP/state/current/colors.toml" ] || fail "current does not resolve to the pack"
[ -f "$TMP/state/ghostty.conf" ] || fail "no ghostty fragment in the state directory"
grep -q '^background = #1e1e2e$' "$TMP/state/ghostty.conf" || fail "the ghostty fragment is wrong"
ok "current resolves to the pack and the Ghostty fragment is in place"

# The state mac-themer publishes is entirely its own. If a previous setup's
# convention ever comes back, this is where it would show up.
[ -e "$TMP/omarchy" ] && fail "something wrote an omarchy directory"
for stray in "$TMP/state/theme" "$TMP/state/sketchybar.sh" "$TMP/state/borders.sh"; do
  [ -e "$stray" ] && fail "unexpected published file: $stray"
done
ok "nothing outside mac-themer's own state was written"

"$cli" next >/dev/null
[ "$("$cli" current)" = "gruvbox" ] || fail "next did not advance the pack"
# four packs, so three more steps come back round to where this started
"$cli" next >/dev/null && "$cli" next >/dev/null && "$cli" next >/dev/null
[ "$("$cli" current)" = "catppuccin" ] || fail "next did not wrap around"
"$sandbox/bin/theme-set" tokyo-night >/dev/null
[ "$("$cli" current)" = "tokyo-night" ] || fail "the theme-set wrapper did not apply a pack"
[ "$("$sandbox/bin/theme-next" | head -1)" != "" ] || fail "the theme-next wrapper produced nothing"
ok "next wraps, and the theme-set/theme-next wrappers work"

first="$("$cli" bg-next | sed 's/^background: //; s/ .*//')"
second="$("$cli" bg-next | sed 's/^background: //; s/ .*//')"
third="$("$cli" bg-next | sed 's/^background: //; s/ .*//')"
[ "$first" != "$second" ] || fail "bg-next did not cycle ($first)"
[ "$third" = "$first" ] || fail "bg-next did not wrap ($first -> $second -> $third)"
ok "bg-next cycles and wraps ($first -> $second -> $third)"

"$cli" render catppuccin | grep -q 'already current' || fail "render is not idempotent"
ok "render is idempotent"

"$cli" list --json | python3 -c 'import json,sys; assert len(json.load(sys.stdin)) == 4' \
  || fail "list --json is wrong"
"$cli" dump --json | python3 -c 'import json,sys; assert json.load(sys.stdin)["slug"]' \
  || fail "dump --json is wrong"
"$cli" doctor >/dev/null || fail "doctor failed"
ok "list, dump and doctor run"

if [ "${MACTHEMER_TEST_BUILD:-0}" = 1 ]; then
  step "borders.swift compiles"
  swiftc -O -F /System/Library/PrivateFrameworks -framework SkyLight \
    -o "$TMP/borders-check" "$REPO_DIR/borders/borders.swift" || fail "swiftc rejected borders.swift"
  ok "swiftc accepted borders.swift"
else
  printf '\033[1;33m==>\033[0m skipped the swiftc build (MACTHEMER_TEST_BUILD=1 to include it)\n'
fi

printf '\n\033[1;32mall mac-themer checks passed\033[0m\n'

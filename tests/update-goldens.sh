#!/usr/bin/env bash
# Regenerate tests/golden from the current renderers.
#
# Run this only when a renderer change is intended. The diff it produces is the
# visual change, so review it the way you would review a screenshot: the whole
# point of the goldens is that restyling the desktop cannot happen by accident.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"

python3 - "$REPO_DIR" <<'PY'
import pathlib
import sys

repo = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(repo / "lib"))

from macthemer import palette, render
from macthemer import tokens as tokens_mod

for slug in palette.available(repo):
    theme = palette.load(repo, slug)
    tokens = tokens_mod.tokens_for(theme)
    bar = tokens_mod.bar_for(theme, tokens)
    files = render.artifacts(theme, tokens, bar)
    files["current.json"] = render.resolved_json(theme, tokens, bar)
    target = repo / "tests" / "golden" / slug
    target.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (target / name).write_text(text)
    print("wrote %s (%d files)" % (target, len(files)))
PY

printf '\nNow check the diff:\n  git diff --stat tests/golden\n'

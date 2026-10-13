#!/usr/bin/env python3
"""mac-themer's unit, golden and no-visual-regression checks.

Run through tests/run.sh, which points MACTHEMER_* at a throwaway tree so a
test run never touches the real desktop. Two suites here are the point of the
file: the pinned colours at the bottom were read off the machine before the
theming moved, so a change to the derivation that would restyle the desktop
fails here instead of being noticed weeks later, and OwnnessTest keeps another
project's paths out of the code entirely.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from macthemer import apply as apply_mod  # noqa: E402
from macthemer import palette, paths, render  # noqa: E402
from macthemer import tokens as tokens_mod  # noqa: E402

SLUGS = ("catppuccin", "gruvbox", "osaka-jade", "tokyo-night")
GENERATED = ("colors.toml", "ghostty.conf")

# The colours the desktop was wearing before the theming moved, read off the
# live configuration. Hex here, where the old bar palette spoke 0xAARRGGBB.
PINNED = {
    "catppuccin": {
        "alpha_byte": 230,
        "bar": {"background": "#1e1e2e", "background_solid": "#1e1e2e",
                "item_bg": "#313244", "accent": "#cba6f7",
                "label": "#cdd6f4", "icon": "#cdd6f4", "muted": "#6c7086",
                "red": "#f38ba8", "green": "#a6e3a1", "yellow": "#f9e2af"},
        "border": {"active": "#cba6f7", "inactive": "#45475a"},
    },
    "gruvbox": {
        "alpha_byte": 230,
        "bar": {"background": "#282828", "background_solid": "#282828",
                "item_bg": "#3c3836", "accent": "#fe8019",
                "label": "#ebdbb2", "icon": "#ebdbb2", "muted": "#928374",
                "red": "#fb4934", "green": "#b8bb26", "yellow": "#fabd2f"},
        "border": {"active": "#fe8019", "inactive": "#504945"},
    },
    "osaka-jade": {
        "alpha_byte": 230,
        "bar": {"background": "#111c18", "background_solid": "#111c18",
                "item_bg": "#23372b", "accent": "#509475",
                "label": "#c1c497", "icon": "#c1c497", "muted": "#53685b",
                "red": "#ff5345", "green": "#63b07a", "yellow": "#e5c736"},
        "border": {"active": "#509475", "inactive": "#23372b"},
    },
    "tokyo-night": {
        "alpha_byte": 230,
        "bar": {"background": "#1a1b26", "background_solid": "#1a1b26",
                "item_bg": "#292e42", "accent": "#7aa2f7",
                "label": "#c0caf5", "icon": "#c0caf5", "muted": "#565f89",
                "red": "#f7768e", "green": "#9ece6a", "yellow": "#e0af68"},
        "border": {"active": "#7aa2f7", "inactive": "#3b4261"},
    },
}

# Assembled rather than written out, so this file does not contain the string
# it searches for: the scan below would otherwise fail on its own needle.
FORBIDDEN = "omacos" + "y"

SCANNED_NAMES = ("install.sh", "uninstall.sh", "theme.schema.json", ".gitignore")
SCANNED_DIRS = ("bin", "lib", "borders", "helper", "tests")
SCANNED_SUFFIXES = (".py", ".sh", ".swift", ".json", ".toml")


class PackTest(unittest.TestCase):
    def test_every_pack_loads(self):
        self.assertEqual(sorted(palette.available(ROOT)), sorted(SLUGS))
        for slug in SLUGS:
            theme = palette.load(ROOT, slug)
            self.assertEqual(theme.slug, slug)
            self.assertEqual(theme.variant, "dark")
            self.assertTrue(theme.name)

    def test_palette_is_complete(self):
        for slug in SLUGS:
            theme = palette.load(ROOT, slug)
            self.assertEqual(sorted(theme.palette), sorted(palette.PALETTE_KEYS))

    def test_missing_palette_key_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "broken", '[palette]\nbackground = "#000000"\n'
                                     '[border]\nactive = "#000000"\ninactive = "#000000"\n')
            with self.assertRaises(palette.ThemeError):
                palette.load(tmp, "broken")

    def test_bad_hex_is_rejected(self):
        import tempfile
        body = ['name = "T"', "[palette]"]
        for key in palette.PALETTE_KEYS:
            value = "not-a-colour" if key == "cursor" else "#101010"
            body.append('%s = "%s"' % (key, value))
        body += ["[border]", 'active = "#101010"', 'inactive = "#101010"']
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "broken", "\n".join(body) + "\n")
            with self.assertRaises(palette.ThemeError):
                palette.load(tmp, "broken")

    def test_unknown_bar_key_is_rejected(self):
        import tempfile
        body = ['name = "T"', "[palette]"]
        for key in palette.PALETTE_KEYS:
            body.append('%s = "#101010"' % key)
        body += ["[border]", 'active = "#101010"', 'inactive = "#101010"',
                 "[bar]", 'chartreuse = "#00ff00"']
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "broken", "\n".join(body) + "\n")
            with self.assertRaises(palette.ThemeError):
                palette.load(tmp, "broken")

    def test_unknown_slug_names_the_directory(self):
        with self.assertRaises(palette.ThemeError):
            palette.load(ROOT, "does-not-exist")


def write_pack(root, slug, body):
    folder = Path(root) / "themes" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.toml").write_text(body)
    return folder


class ColourTest(unittest.TestCase):
    def test_mix_endpoints(self):
        self.assertEqual(palette.mix("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(palette.mix("#000000", "#ffffff", 1.0), "#ffffff")

    def test_mix_is_srgb_not_linear(self):
        # A quarter of the way from black to white is 64 in sRGB. Mixing in
        # linear light would give 137, which is why the choice is asserted: the
        # elevation ramp has to stay in the space the palette was picked in.
        self.assertEqual(palette.mix("#000000", "#ffffff", 0.25), "#404040")

    def test_alpha_byte(self):
        self.assertEqual(palette.alpha_byte(0.0), 0)
        self.assertEqual(palette.alpha_byte(1.0), 255)
        self.assertEqual(palette.alpha_byte(0.902), 230)  # 0xe6, as shipped
        with self.assertRaises(palette.ThemeError):
            palette.alpha_byte(1.5)

    def test_argb(self):
        self.assertEqual(palette.argb("#1e1e2e"), 0xFF1E1E2E)
        self.assertEqual(palette.argb("#1e1e2e", 0.902), 0xE61E1E2E)


class TokenTest(unittest.TestCase):
    def setUp(self):
        self.theme = palette.load(ROOT, "catppuccin")
        self.tokens = tokens_mod.tokens_for(self.theme)

    def test_roles_are_complete(self):
        self.assertEqual(list(self.tokens), list(tokens_mod.TOKEN_ORDER))

    def test_semantic_roles_come_from_the_ansi_ramp(self):
        keys = self.theme.palette
        self.assertEqual(self.tokens["surface"], keys["background"])
        self.assertEqual(self.tokens["on_surface"], keys["foreground"])
        self.assertEqual(self.tokens["primary"], keys["accent"])
        self.assertEqual(self.tokens["error"], keys["color1"])
        self.assertEqual(self.tokens["success"], keys["color2"])
        self.assertEqual(self.tokens["warning"], keys["color3"])
        self.assertEqual(self.tokens["info"], keys["color4"])
        self.assertEqual(self.tokens["secondary"], keys["color6"])

    def test_pack_overrides_win(self):
        self.assertEqual(self.tokens["surface_container"], "#313244")
        self.assertEqual(self.tokens["muted"], "#6c7086")

    def test_elevation_is_ordered(self):
        ramp = [self.tokens[role] for role in
                ("surface", "surface_container_low", "surface_container",
                 "surface_container_high", "surface_container_highest", "on_surface")]
        luminance = [int(colour[1:3], 16) + int(colour[3:5], 16) + int(colour[5:7], 16)
                     for colour in ramp]
        self.assertEqual(luminance, sorted(luminance))

    def test_bar_uses_the_bright_ramp(self):
        bar = tokens_mod.bar_for(self.theme, self.tokens)
        self.assertEqual(bar["red"], self.theme.palette["color9"])
        self.assertEqual(bar["green"], self.theme.palette["color10"])
        self.assertEqual(bar["yellow"], self.theme.palette["color11"])
        self.assertEqual(bar["accent"], self.tokens["primary"])
        self.assertEqual(bar["item_bg"], self.tokens["surface_container"])

    def test_bar_override_beats_the_bright_ramp(self):
        theme = palette.load(ROOT, "osaka-jade")
        bar = tokens_mod.bar_for(theme, tokens_mod.tokens_for(theme))
        self.assertEqual(bar["red"], "#ff5345")
        self.assertNotEqual(bar["red"], theme.palette["color9"])

    def test_alpha_defaults(self):
        self.assertEqual(tokens_mod.background_alpha(self.theme), 0.902)


class SchemaTest(unittest.TestCase):
    """The published schema and the loader must not drift apart."""

    def setUp(self):
        self.schema = json.loads((ROOT / "theme.schema.json").read_text())

    def test_palette_keys_match(self):
        self.assertEqual(sorted(self.schema["properties"]["palette"]["required"]),
                         sorted(palette.PALETTE_KEYS))

    def test_border_keys_match(self):
        self.assertEqual(sorted(self.schema["properties"]["border"]["required"]),
                         ["active", "inactive"])

    def test_bar_keys_match(self):
        expected = sorted(palette.BAR_COLOR_KEYS + ("background_alpha",))
        self.assertEqual(sorted(self.schema["properties"]["bar"]["properties"]), expected)

    def test_required_sections_match(self):
        self.assertEqual(sorted(self.schema["required"]), ["border", "name", "palette"])


class GoldenTest(unittest.TestCase):
    def setUp(self):
        self.repo = paths.repo_root()

    def rendered(self, slug):
        theme = palette.load(self.repo, slug)
        tokens = tokens_mod.tokens_for(theme)
        bar = tokens_mod.bar_for(theme, tokens)
        files = render.artifacts(theme, tokens, bar)
        files["current.json"] = render.resolved_json(theme, tokens, bar)
        return files

    def test_renders_match_the_committed_goldens(self):
        for slug in SLUGS:
            for name, text in self.rendered(slug).items():
                golden = self.repo / "tests" / "golden" / slug / name
                self.assertTrue(golden.is_file(), "missing golden %s" % golden)
                self.assertEqual(text, golden.read_text(),
                                 "%s/%s drifted from its golden" % (slug, name))

    def test_pack_directory_matches_its_goldens(self):
        # The files in the pack are generated and gitignored; when they exist
        # they are what consumers are reading right now, so they are checked too.
        for slug in SLUGS:
            for name in GENERATED:
                path = self.repo / "themes" / slug / name
                if not path.is_file():
                    continue
                self.assertEqual(path.read_text(),
                                 (self.repo / "tests" / "golden" / slug / name).read_text(),
                                 "%s/%s on disk is stale" % (slug, name))

    def test_resolved_palette_carries_no_machine_paths(self):
        resolved = json.loads(self.rendered("catppuccin")["current.json"])
        self.assertEqual(resolved["pack"], "themes/catppuccin")
        self.assertEqual(resolved["backgrounds"], "themes/catppuccin/backgrounds")
        self.assertNotIn(str(self.repo), json.dumps(resolved))

    def test_ghostty_uses_hyphenated_names(self):
        # Ghostty's own spelling. The pre-move file used these, and warning about
        # unknown keys on every launch is not a cosmetic difference.
        text = self.rendered("catppuccin")["ghostty.conf"]
        self.assertIn("cursor-color = #", text)
        self.assertIn("selection-background = #", text)
        self.assertIn("selection-foreground = #", text)


class RegressionPinTest(unittest.TestCase):
    """The colours that were on the machine before the theming moved."""

    def resolved(self, slug):
        theme = palette.load(ROOT, slug)
        tokens = tokens_mod.tokens_for(theme)
        return render.resolved(theme, tokens, tokens_mod.bar_for(theme, tokens))

    def test_no_colour_moved(self):
        for slug, expected in PINNED.items():
            resolved = self.resolved(slug)
            self.assertEqual(resolved["alpha_byte"], expected["alpha_byte"], slug)
            for key, value in expected["bar"].items():
                self.assertEqual(resolved["bar"][key], value, "%s bar.%s" % (slug, key))
            for key, value in expected["border"].items():
                self.assertEqual(resolved["border"][key], value, "%s border.%s" % (slug, key))

    def test_every_bar_and_border_key_is_pinned(self):
        # A key added to the bar vocabulary without a pin would be a colour
        # nobody checked. This makes the omission fail instead.
        for slug, expected in PINNED.items():
            resolved = self.resolved(slug)
            self.assertEqual(sorted(resolved["bar"]), sorted(expected["bar"]), slug)
            self.assertEqual(sorted(resolved["border"]), ["active", "inactive"], slug)


class OwnnessTest(unittest.TestCase):
    """mac-themer must not read, write, run or reinstall another project's
    files. Comments are exempt on purpose: the border daemon is a port, and MIT
    requires the attribution to survive, so the only mentions left in code are
    the provenance lines in NOTICE.md and the port's own header."""

    def scanned(self):
        for name in SCANNED_NAMES:
            path = ROOT / name
            if path.is_file():
                yield path
        for folder in SCANNED_DIRS:
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_file() and path.suffix in SCANNED_SUFFIXES:
                    yield path
        for path in sorted((ROOT / "themes").glob("*/theme.toml")):
            yield path

    def test_nothing_references_another_project(self):
        offenders = []
        for path in self.scanned():
            prefixes = ("//", "/*", "*") if path.suffix == ".swift" else ("#",)
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if line.strip().startswith(prefixes):
                    continue
                if FORBIDDEN in line.lower():
                    offenders.append("%s:%d: %s" % (path.relative_to(ROOT), number, line.strip()))
        self.assertEqual(offenders, [],
                         "the themer still points at another project:\n" + "\n".join(offenders))

    def test_notice_keeps_the_attribution(self):
        notice = (ROOT / "NOTICE.md").read_text().lower()
        self.assertIn(FORBIDDEN, notice)
        self.assertIn("mit", notice)

    def test_no_hidden_install_hooks(self):
        # Nothing may shell out to a package manager or another updater.
        # Assembled so this check does not match its own list of needles.
        banned = ("bre" + "w ", "git " + "pull", "git " + "-C",
                  "cur" + "l ", "wge" + "t ")
        for path in self.scanned():
            if path.suffix not in (".sh", ".py"):
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if line.strip().startswith("#"):
                    continue
                for needle in banned:
                    if needle in line and "noqa" not in line:
                        self.fail("%s:%d runs %r" % (path.relative_to(ROOT), number, needle))


class WriteTest(unittest.TestCase):
    def test_write_if_changed_reports_the_second_write(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "file"
            self.assertTrue(apply_mod.write_if_changed(target, "one"))
            self.assertFalse(apply_mod.write_if_changed(target, "one"))
            self.assertTrue(apply_mod.write_if_changed(target, "two"))
            self.assertEqual(target.read_text(), "two")

    def test_relink_replaces_and_reports(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "link"
            real = Path(tmp) / "real"
            real.mkdir()
            self.assertTrue(apply_mod.relink(target, real))
            self.assertFalse(apply_mod.relink(target, real))
            self.assertTrue(target.is_symlink())

    def test_relink_refuses_a_real_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "dir"
            target.mkdir()
            with self.assertRaises(RuntimeError):
                apply_mod.relink(target, Path(tmp))

    def test_backgrounds_are_sorted_and_filtered(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "themes" / "t" / "backgrounds"
            folder.mkdir(parents=True)
            for name in ("2-b.png", "0-a.webp", "1-c.jpg", "notes.txt"):
                (folder / name).write_text("x")
            theme = palette.Theme(slug="t", name="T", variant="dark", palette={},
                                  border={}, token_overrides={}, bar={},
                                  source=Path(tmp) / "themes" / "t" / "theme.toml")
            names = [path.name for path in apply_mod.backgrounds(theme)]
            self.assertEqual(names, ["0-a.webp", "1-c.jpg", "2-b.png"])

    def test_wallpaper_helper_prefers_our_own_binary(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / apply_mod.WALLPAPER_HELPER
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            previous = __import__("os").environ.get("MACTHEMER_BIN")
            __import__("os").environ["MACTHEMER_BIN"] = tmp
            try:
                self.assertEqual(apply_mod.wallpaper_helper(), binary)
            finally:
                if previous is None:
                    del __import__("os").environ["MACTHEMER_BIN"]
                else:
                    __import__("os").environ["MACTHEMER_BIN"] = previous


if __name__ == "__main__":
    unittest.main()

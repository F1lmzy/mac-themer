#!/usr/bin/env python3
"""mac-themer's unit, golden and no-visual-regression checks.

Run through tests/run.sh, which points MACTHEMER_* at a throwaway tree so a
test run never touches the real desktop. The pinned values at the bottom are
the point of the suite: every one of them was read off the machine before the
move, so a change to the derivation that would restyle a bar or a ring fails
here instead of being noticed weeks later.
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
GENERATED = ("colors.toml", "ghostty.conf", "sketchybar.sh", "borders.sh")

# Read off the pre-move machine: omacosy's themes/<slug>/sketchybar.sh and
# borders.sh. Byte-for-byte, minus the comment line.
PINNED = {
    "catppuccin": {
        "sketchybar.sh": {
            "BAR_COLOR": "0xe61e1e2e", "BAR_BG_SOLID": "0xff1e1e2e",
            "ITEM_BG": "0xff313244", "ACCENT": "0xffcba6f7",
            "LABEL_COLOR": "0xffcdd6f4", "ICON_COLOR": "0xffcdd6f4",
            "MUTED": "0xff6c7086", "RED": "0xfff38ba8",
            "GREEN": "0xffa6e3a1", "YELLOW": "0xfff9e2af",
        },
        "borders.sh": {"ACTIVE_COLOR": "0xffcba6f7", "INACTIVE_COLOR": "0xff45475a"},
    },
    "gruvbox": {
        "sketchybar.sh": {
            "BAR_COLOR": "0xe6282828", "BAR_BG_SOLID": "0xff282828",
            "ITEM_BG": "0xff3c3836", "ACCENT": "0xfffe8019",
            "LABEL_COLOR": "0xffebdbb2", "ICON_COLOR": "0xffebdbb2",
            "MUTED": "0xff928374", "RED": "0xfffb4934",
            "GREEN": "0xffb8bb26", "YELLOW": "0xfffabd2f",
        },
        "borders.sh": {"ACTIVE_COLOR": "0xfffe8019", "INACTIVE_COLOR": "0xff504945"},
    },
    "osaka-jade": {
        "sketchybar.sh": {
            "BAR_COLOR": "0xe6111c18", "BAR_BG_SOLID": "0xff111c18",
            "ITEM_BG": "0xff23372b", "ACCENT": "0xff509475",
            "LABEL_COLOR": "0xffc1c497", "ICON_COLOR": "0xffc1c497",
            "MUTED": "0xff53685b", "RED": "0xffff5345",
            "GREEN": "0xff63b07a", "YELLOW": "0xffe5c736",
        },
        "borders.sh": {"ACTIVE_COLOR": "0xff509475", "INACTIVE_COLOR": "0xff23372b"},
    },
    "tokyo-night": {
        "sketchybar.sh": {
            "BAR_COLOR": "0xe61a1b26", "BAR_BG_SOLID": "0xff1a1b26",
            "ITEM_BG": "0xff292e42", "ACCENT": "0xff7aa2f7",
            "LABEL_COLOR": "0xffc0caf5", "ICON_COLOR": "0xffc0caf5",
            "MUTED": "0xff565f89", "RED": "0xfff7768e",
            "GREEN": "0xff9ece6a", "YELLOW": "0xffe0af68",
        },
        "borders.sh": {"ACTIVE_COLOR": "0xff7aa2f7", "INACTIVE_COLOR": "0xff3b4261"},
    },
}

GOOD_PACK = {
    "name": "Test",
    "palette": {
        "background": "#101010", "foreground": "#e0e0e0", "cursor": "#ffffff",
        "accent": "#4080ff", "selection_background": "#303030",
        "selection_foreground": "#e0e0e0",
        **{"color%d" % i: "#%02x%02x%02x" % (i * 16, 255 - i * 16, 128) for i in range(16)},
    },
    "border": {"active": "#4080ff", "inactive": "#303030"},
}


def exports(text):
    found = {}
    for line in text.splitlines():
        if line.startswith("export ") and "=" in line:
            name, value = line[len("export "):].split("=", 1)
            found[name] = value
    return found


def write_pack(root, slug, body):
    folder = Path(root) / "themes" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.toml").write_text(body)
    return folder


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
            write_pack(tmp, "broken", '[palette]\nbackground = "#000000"\n[border]\nactive = "#000000"\ninactive = "#000000"\n')
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


class ColourTest(unittest.TestCase):
    def test_mix_endpoints(self):
        self.assertEqual(palette.mix("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(palette.mix("#000000", "#ffffff", 1.0), "#ffffff")

    def test_mix_is_srgb_not_linear(self):
        # A quarter of the way from black to white is 64 in sRGB. Mixing in
        # linear light would give 137, which is why the choice is asserted:
        # the elevation ramp has to stay in the space the palette was picked in.
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
        palette_keys = self.theme.palette
        self.assertEqual(self.tokens["surface"], palette_keys["background"])
        self.assertEqual(self.tokens["on_surface"], palette_keys["foreground"])
        self.assertEqual(self.tokens["primary"], palette_keys["accent"])
        self.assertEqual(self.tokens["error"], palette_keys["color1"])
        self.assertEqual(self.tokens["success"], palette_keys["color2"])
        self.assertEqual(self.tokens["warning"], palette_keys["color3"])
        self.assertEqual(self.tokens["info"], palette_keys["color4"])
        self.assertEqual(self.tokens["secondary"], palette_keys["color6"])

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
        # Ghostty's own spelling. The pre-move file used these, and warning
        # about unknown keys on every launch is not a cosmetic difference.
        text = self.rendered("catppuccin")["ghostty.conf"]
        self.assertIn("cursor-color = #", text)
        self.assertIn("selection-background = #", text)
        self.assertIn("selection-foreground = #", text)


class RegressionPinTest(unittest.TestCase):
    """The colours that were on the machine before the move."""

    def rendered(self, slug):
        theme = palette.load(ROOT, slug)
        tokens = tokens_mod.tokens_for(theme)
        return render.artifacts(theme, tokens, tokens_mod.bar_for(theme, tokens))

    def test_no_colour_moved(self):
        for slug, files in PINNED.items():
            rendered = self.rendered(slug)
            for name, expected in files.items():
                self.assertEqual(exports(rendered[name]), expected,
                                 "%s/%s no longer matches the pre-move palette" % (slug, name))


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
            (Path(tmp) / "themes" / "t" / "theme.toml").write_text("")
            theme = palette.Theme(slug="t", name="T", variant="dark", palette={},
                                  border={}, token_overrides={}, bar={},
                                  source=Path(tmp) / "themes" / "t" / "theme.toml")
            names = [path.name for path in apply_mod.backgrounds(theme)]
            self.assertEqual(names, ["0-a.webp", "1-c.jpg", "2-b.png"])


if __name__ == "__main__":
    unittest.main()

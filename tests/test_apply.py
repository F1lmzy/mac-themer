#!/usr/bin/env python3
"""The guarded `apply` command: one exact pack, only after a full palette check.

`catalog` is the read side of the shared theme browse. `apply` is the write
side. It reloads the same strict catalog, selects one exact slug and refuses to
write anything until the resolved, path-free palette still equals the copy the
consumer sent. These tests pin that the check is the authorization: a stale or
forged palette, a path-shaped slug and an oversized document must all be
rejected before any desktop state is touched.

Run through tests/run.sh, which points MACTHEMER_* at a throwaway tree.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from importlib.machinery import SourceFileLoader
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from macthemer import palette, render  # noqa: E402
from macthemer import tokens as tokens_mod  # noqa: E402

MAX_EXPECTED_BYTES = 65536


def palette_body(name="Apply Test", accent="#202020"):
    lines = ['name = "%s"' % name, 'variant = "dark"', "[palette]"]
    for key in palette.PALETTE_KEYS:
        lines.append('%s = "%s"' % (key, accent if key == "accent" else "#101010"))
    lines += ["[border]", 'active = "#303030"', 'inactive = "#313131"']
    return "\n".join(lines) + "\n"


def write_pack(themes, slug, body=None):
    folder = Path(themes) / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.toml").write_text(body if body is not None else palette_body())
    return folder


def write_backgrounds(folder, names):
    backgrounds = folder / "backgrounds"
    backgrounds.mkdir(parents=True, exist_ok=True)
    for name in names:
        (backgrounds / name).write_bytes(b"x")
    return backgrounds


def entry_for(themes, slug):
    theme = next(theme for theme in palette.catalog(themes) if theme.slug == slug)
    tokens = tokens_mod.tokens_for(theme)
    return render.palette_entry(theme, tokens, tokens_mod.bar_for(theme, tokens))


def load_cli():
    loader = SourceFileLoader("mac_themer_cli", str(ROOT / "bin" / "mac-themer"))
    spec = importlib.util.spec_from_loader("mac_themer_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ApplyGuardTest(unittest.TestCase):
    """The guard logic, exercised in-process with the writer mocked out."""

    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.themes = Path(self.tmp.name) / "themes"
        write_pack(self.themes, "only-pack")
        self.entry = entry_for(self.themes, "only-pack")

    def run_apply(self, slug="only-pack", expected=None, raw=None, background=None):
        if raw is None:
            raw = json.dumps(self.entry if expected is None else expected)
        args = Namespace(slug=slug, expected_palette=raw, background=background, json=True)
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"MACTHEMER_THEMES": str(self.themes)}), \
                contextlib.redirect_stdout(out):
            code = self.cli.cmd_apply(args)
        return code, out.getvalue()

    def test_matching_palette_applies_exact_pack_without_wallpaper(self):
        recorded = {}

        def fake_apply(theme, **kwargs):
            recorded["theme"] = theme
            recorded["kwargs"] = kwargs
            return ["wrote current.json"]

        with mock.patch.object(self.cli.apply_mod, "apply", side_effect=fake_apply):
            code, out = self.run_apply()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"schema": 1, "status": "applied",
                                           "theme": "only-pack", "wallpaper": None,
                                           "warnings": []})
        self.assertEqual(recorded["theme"].slug, "only-pack")
        self.assertEqual(recorded["theme"].source.parent, self.themes.resolve() / "only-pack")
        self.assertEqual(recorded["kwargs"].get("wallpaper"), False)
        self.assertEqual(recorded["kwargs"].get("background"), None)

    def test_background_flag_sets_one_of_the_packs_wallpapers(self):
        folder = self.themes / "only-pack"
        write_backgrounds(folder, ["2-b.webp", "1-a.webp"])
        recorded = {}

        def fake_apply(theme, **kwargs):
            recorded["kwargs"] = kwargs
            return ["wrote current.json",
                    "wallpaper via macthemer-wallpaper (%s)" % kwargs["background"].name]

        with mock.patch.object(self.cli.apply_mod, "apply", side_effect=fake_apply):
            code, out = self.run_apply(background="2-b.webp")
        self.assertEqual(code, 0)
        document = json.loads(out)
        self.assertEqual(document["wallpaper"], "2-b.webp")
        self.assertEqual(document["warnings"], [])
        self.assertEqual(recorded["kwargs"]["wallpaper"], True)
        self.assertEqual(recorded["kwargs"]["background"].name, "2-b.webp")
        self.assertEqual(recorded["kwargs"]["background"].parent,
                         (folder / "backgrounds").resolve())

    def test_unknown_and_path_shaped_backgrounds_are_rejected_before_apply(self):
        write_backgrounds(self.themes / "only-pack", ["1-a.webp"])
        for ident in ("2-b.webp", "../1-a.webp", "1-a.webp/..", "notes.txt", ""):
            with self.subTest(ident=ident), \
                    mock.patch.object(self.cli.apply_mod, "apply") as apply:
                with self.assertRaises(SystemExit):
                    self.run_apply(background=ident)
            apply.assert_not_called()

    def test_a_wallpaper_that_could_not_be_set_is_reported_as_a_warning(self):
        write_backgrounds(self.themes / "only-pack", ["1-a.webp"])
        with mock.patch.object(self.cli.apply_mod, "apply",
                               return_value=["wrote current.json", "wallpaper failed (1-a.webp)"]):
            _, out = self.run_apply(background="1-a.webp")
        document = json.loads(out)
        self.assertIsNone(document["wallpaper"])
        self.assertEqual(document["warnings"], ["wallpaperFailed"])

    def test_ghostty_and_wallpaper_warnings_are_reported_together(self):
        write_backgrounds(self.themes / "only-pack", ["1-a.webp"])
        with mock.patch.object(self.cli.apply_mod, "apply",
                               return_value=["ghostty reload failed (reload manually)",
                                             "wallpaper via osascript (1-a.webp)"]):
            _, out = self.run_apply(background="1-a.webp")
        document = json.loads(out)
        self.assertEqual(document["wallpaper"], "1-a.webp")
        self.assertEqual(document["warnings"], ["ghosttyReloadFailed"])

    def test_success_json_never_carries_paths_or_actions(self):
        write_backgrounds(self.themes / "only-pack", ["1-a.webp"])
        with mock.patch.object(self.cli.apply_mod, "apply",
                               return_value=["wrote current.json", "wrote ghostty.conf",
                                             "wallpaper via macthemer-wallpaper (1-a.webp)"]):
            _, out = self.run_apply(background="1-a.webp")
        self.assertNotIn(self.tmp.name, out)
        self.assertNotIn("current.json", out)
        self.assertNotIn("ghostty", out)
        self.assertNotIn("backgrounds/", out)

    def test_stale_palette_is_rejected_before_apply(self):
        stale = dict(self.entry, palette=dict(self.entry["palette"], accent="#ffffff"))
        with mock.patch.object(self.cli.apply_mod, "apply") as apply:
            with self.assertRaises(SystemExit):
                self.run_apply(expected=stale)
        apply.assert_not_called()

    def test_extra_fields_are_rejected(self):
        forged = dict(self.entry, pack="themes/only-pack")
        with mock.patch.object(self.cli.apply_mod, "apply") as apply:
            with self.assertRaises(SystemExit):
                self.run_apply(expected=forged)
        apply.assert_not_called()

    def test_missing_fields_are_rejected(self):
        forged = {key: value for key, value in self.entry.items() if key != "tokens"}
        with mock.patch.object(self.cli.apply_mod, "apply") as apply:
            with self.assertRaises(SystemExit):
                self.run_apply(expected=forged)
        apply.assert_not_called()

    def test_nonintegral_alpha_is_rejected(self):
        forged = dict(self.entry, alpha_byte=float(self.entry["alpha_byte"]))
        with mock.patch.object(self.cli.apply_mod, "apply") as apply:
            with self.assertRaises(SystemExit):
                self.run_apply(expected=forged)
        apply.assert_not_called()

    def test_path_shaped_and_unknown_slugs_are_rejected(self):
        for slug in ("../evil", "Only-Pack", "only-pack/..", "a" * 129, "missing"):
            with self.subTest(slug=slug), mock.patch.object(self.cli.apply_mod, "apply") as apply:
                with self.assertRaises(SystemExit):
                    self.run_apply(slug=slug)
            apply.assert_not_called()

    def test_oversized_expected_palette_is_rejected(self):
        raw = json.dumps(self.entry) + " " * (MAX_EXPECTED_BYTES + 1)
        with mock.patch.object(self.cli.apply_mod, "apply") as apply:
            with self.assertRaises(SystemExit):
                self.run_apply(raw=raw)
        apply.assert_not_called()

    def test_malformed_expected_palette_is_rejected(self):
        for raw in ("{", "[]", '"pack"', "null"):
            with self.subTest(raw=raw), mock.patch.object(self.cli.apply_mod, "apply") as apply:
                with self.assertRaises(SystemExit):
                    self.run_apply(raw=raw)
            apply.assert_not_called()

    def test_reload_failure_is_reported_as_a_warning(self):
        with mock.patch.object(self.cli.apply_mod, "apply",
                               return_value=["wrote current.json",
                                             "ghostty reload failed (reload manually)"]):
            _, out = self.run_apply()
        self.assertEqual(json.loads(out)["warnings"], ["ghosttyReloadFailed"])


class ApplyCliTest(unittest.TestCase):
    """The command end to end, on a throwaway tree that never touches the desktop."""

    def sandbox_env(self, root, themes):
        env = dict(os.environ)
        env.update({
            "MACTHEMER_REPO": str(ROOT),
            "MACTHEMER_DRY_RUN": "1",
            "MACTHEMER_THEMES": str(themes),
            "MACTHEMER_STATE": str(root / "state"),
            "MACTHEMER_RUN": str(root / "run"),
            "MACTHEMER_HOME": str(root / "home"),
            "MACTHEMER_BIN": str(root / "bin"),
        })
        return env

    def run_cli(self, env, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin" / "mac-themer"), *args],
                              capture_output=True, text=True, env=env, timeout=30)

    def test_cli_apply_writes_only_owned_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            write_pack(themes, "only-pack", palette_body(name="Only Pack", accent="#123456"))
            entry = entry_for(themes, "only-pack")
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "apply", "only-pack",
                                  "--expected-palette", json.dumps(entry), "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(document, {"schema": 1, "status": "applied",
                                        "theme": "only-pack", "wallpaper": None,
                                        "warnings": []})
            self.assertNotIn(str(root), result.stdout)
            applied = json.loads((root / "state" / "current.json").read_text())
            self.assertEqual(applied["slug"], "only-pack")
            self.assertEqual(applied["palette"]["accent"], "#123456")
            # apply never changes the wallpaper, so no background is remembered.
            self.assertFalse((root / "run" / "background").exists())

    def test_cli_apply_with_a_background_sets_it_from_the_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            folder = write_pack(themes, "only-pack", palette_body(accent="#123456"))
            write_backgrounds(folder, ["2-b.webp", "1-a.jpg", "notes.txt", ".DS_Store"])
            entry = entry_for(themes, "only-pack")
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "apply", "only-pack",
                                  "--expected-palette", json.dumps(entry),
                                  "--background", "2-b.webp", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            self.assertEqual(document["wallpaper"], "2-b.webp")
            self.assertEqual(document["warnings"], [])
            self.assertNotIn(str(root), result.stdout)
            # The remembered background points at this pack's own image.
            link = root / "run" / "background"
            self.assertEqual(Path(os.readlink(link)).resolve(),
                             (folder / "backgrounds" / "2-b.webp").resolve())

    def test_cli_apply_rejects_a_background_from_another_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            write_backgrounds(write_pack(themes, "only-pack"), ["1-a.webp"])
            write_backgrounds(write_pack(themes, "other-pack"), ["9-z.webp"])
            entry = entry_for(themes, "only-pack")
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "apply", "only-pack",
                                  "--expected-palette", json.dumps(entry),
                                  "--background", "9-z.webp", "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mac-themer:", result.stderr)
            self.assertFalse((root / "state").exists())

    def test_cli_apply_rejects_stale_palette_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            write_pack(themes, "only-pack", palette_body(accent="#123456"))
            entry = entry_for(themes, "only-pack")
            entry["palette"]["accent"] = "#ffffff"
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "apply", "only-pack",
                                  "--expected-palette", json.dumps(entry), "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("mac-themer:", result.stderr)
            self.assertFalse((root / "state").exists())

    def test_cli_apply_requires_expected_palette(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            write_pack(themes, "only-pack")
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "apply", "only-pack", "--json")
            self.assertNotEqual(result.returncode, 0)


class WallpaperCliTest(unittest.TestCase):
    """Setting one wallpaper by identity, leaving the theme exactly as it was."""

    def sandbox_env(self, root, themes):
        env = dict(os.environ)
        env.update({
            "MACTHEMER_REPO": str(ROOT),
            "MACTHEMER_DRY_RUN": "1",
            "MACTHEMER_THEMES": str(themes),
            "MACTHEMER_STATE": str(root / "state"),
            "MACTHEMER_RUN": str(root / "run"),
            "MACTHEMER_HOME": str(root / "home"),
            "MACTHEMER_BIN": str(root / "bin"),
        })
        return env

    def run_cli(self, env, *args):
        return subprocess.run([sys.executable, str(ROOT / "bin" / "mac-themer"), *args],
                              capture_output=True, text=True, env=env, timeout=30)

    def test_sets_the_packs_image_and_reports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            folder = write_pack(themes, "only-pack")
            write_backgrounds(folder, ["1-a.jpg", "2-b.webp", "notes.txt"])
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "wallpaper", "only-pack", "--id", "2-b.webp", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             {"schema": 1, "status": "set", "theme": "only-pack",
                              "wallpaper": "2-b.webp", "warnings": []})
            self.assertNotIn(str(root), result.stdout)
            link = root / "run" / "background"
            self.assertEqual(Path(os.readlink(link)).resolve(),
                             (folder / "backgrounds" / "2-b.webp").resolve())
            # A wallpaper change is not a theme change: nothing else is written.
            self.assertFalse((root / "state").exists())

    def test_rejects_ids_the_pack_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            folder = write_pack(themes, "only-pack")
            write_backgrounds(folder, ["1-a.jpg"])
            env = self.sandbox_env(root, themes)
            for ident in ("2-b.webp", "../1-a.jpg", "notes.txt", "", "1-a.jpg/.."):
                with self.subTest(ident=ident):
                    result = self.run_cli(env, "wallpaper", "only-pack",
                                          "--id", ident, "--json")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("mac-themer:", result.stderr)
            self.assertFalse((root / "run").exists())

    def test_rejects_an_unknown_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            themes = root / "themes"
            write_backgrounds(write_pack(themes, "only-pack"), ["1-a.jpg"])
            env = self.sandbox_env(root, themes)
            result = self.run_cli(env, "wallpaper", "ghost", "--id", "1-a.jpg", "--json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown theme", result.stderr)


if __name__ == "__main__":
    unittest.main()

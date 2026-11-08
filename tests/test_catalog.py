#!/usr/bin/env python3
"""The read-only catalog: every pack's resolved palette in one document.

The catalog exists so a consumer can build a theme browser without reading
TOML, following the active-theme symlink, or running any helper. These tests
pin that it stays read-only, path-free, deterministic and bounded, and that it
fails loudly on a broken pack instead of quietly publishing a partial list.

Run through tests/run.sh, which points MACTHEMER_* at a throwaway tree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from macthemer import palette, render  # noqa: E402
from macthemer import apply as apply_mod  # noqa: E402
from macthemer import tokens as tokens_mod  # noqa: E402

SLUGS = ("catppuccin", "gruvbox", "osaka-jade", "tokyo-night")
ENTRY_FIELDS = ("schema", "slug", "name", "variant", "alpha_byte",
                "palette", "tokens", "border", "bar")

# What the desktop wore before the theming moved. The catalog has to carry the
# same resolved colour the published current.json does, not a re-derivation.
CATPPUCCIN_ACCENT = "#cba6f7"
CATPPUCCIN_ALPHA = 230


def palette_body(name="Catalog Test", accent="#202020"):
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


def run_with_deadline(call, seconds=10):
    """Run *call* in a daemon thread so a blocking read fails instead of hanging."""
    outcome = {}

    def target():
        try:
            outcome["value"] = call()
        except BaseException as exc:  # noqa: BLE001 - handed back to the test
            outcome["error"] = exc

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise AssertionError("catalog did not finish within %ss" % seconds)
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


def catalog_entry(theme):
    tokens = tokens_mod.tokens_for(theme)
    return render.palette_entry(theme, tokens, tokens_mod.bar_for(theme, tokens))


def write_backgrounds(folder, names):
    backgrounds = Path(folder) / "backgrounds"
    backgrounds.mkdir(parents=True, exist_ok=True)
    for name in names:
        (backgrounds / name).write_bytes(b"x")
    return backgrounds


def run_cli(themes=None, args=("catalog", "--json"), timeout=20):
    env = dict(os.environ)
    env["MACTHEMER_REPO"] = str(ROOT)
    env["MACTHEMER_DRY_RUN"] = "1"
    sandbox = Path(tempfile.mkdtemp(prefix="mc-catalog-"))
    env["MACTHEMER_STATE"] = str(sandbox / "state")
    env["MACTHEMER_RUN"] = str(sandbox / "run")
    env["MACTHEMER_HOME"] = str(sandbox / "home")
    env["MACTHEMER_BIN"] = str(sandbox / "bin")
    if themes is None:
        env.pop("MACTHEMER_THEMES", None)
    else:
        env["MACTHEMER_THEMES"] = str(themes)
    result = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "mac-themer"), *args],
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    return result, sandbox


class CatalogDocumentTest(unittest.TestCase):
    def test_palette_entry_matches_the_published_document(self):
        for slug in SLUGS:
            theme = palette.load(ROOT, slug)
            tokens = tokens_mod.tokens_for(theme)
            published = render.resolved(theme, tokens, tokens_mod.bar_for(theme, tokens))
            entry = render.palette_entry(theme, tokens, tokens_mod.bar_for(theme, tokens))
            self.assertEqual(sorted(entry), sorted(ENTRY_FIELDS), slug)
            for field in ENTRY_FIELDS:
                self.assertEqual(entry[field], published[field], "%s %s" % (slug, field))
        # The three keys that make the published document a file artifact, not a
        # catalog entry, must not survive the projection.
        for absent in ("generated_by", "pack", "backgrounds"):
            self.assertNotIn(absent, render.palette_entry(
                palette.load(ROOT, "catppuccin"),
                tokens_mod.tokens_for(palette.load(ROOT, "catppuccin")),
                tokens_mod.bar_for(palette.load(ROOT, "catppuccin"),
                                   tokens_mod.tokens_for(palette.load(ROOT, "catppuccin")))))

    def test_catalog_carries_resolved_colours_without_paths(self):
        entries = palette.catalog(ROOT / "themes")
        self.assertEqual([entry.slug for entry in entries], list(SLUGS))
        documents = [catalog_entry(theme) for theme in entries]
        catppuccin = documents[0]
        self.assertEqual(catppuccin["slug"], "catppuccin")
        self.assertEqual(catppuccin["variant"], "dark")
        self.assertEqual(catppuccin["alpha_byte"], CATPPUCCIN_ALPHA)
        self.assertEqual(catppuccin["palette"]["accent"], CATPPUCCIN_ACCENT)
        self.assertEqual(catppuccin["bar"]["accent"], CATPPUCCIN_ACCENT)
        wire = json.dumps(documents)
        self.assertNotIn(str(ROOT), wire)
        self.assertNotIn("generated_by", wire)

    def test_empty_themes_directory_is_an_empty_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(palette.catalog(Path(tmp)), [])

    def test_regular_files_and_hidden_directories_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "notes.txt").write_text("not a pack")
            (Path(tmp) / ".git").mkdir()
            (Path(tmp) / ".git" / "config").write_text("x")
            self.assertEqual(palette.catalog(Path(tmp)), [])


class CatalogRejectionTest(unittest.TestCase):
    def test_invalid_slug_is_rejected(self):
        for bad in ("Catppuccin", "bad slug", "-leading", "_leading", "a" * 129):
            with self.subTest(slug=bad), tempfile.TemporaryDirectory() as tmp:
                write_pack(tmp, bad)
                with self.assertRaises(palette.ThemeError):
                    palette.catalog(Path(tmp))

    def test_names_match_the_published_identity_bounds(self):
        for bad in ("n" * 257, "é" * 129, "bad\\u0000name"):
            with self.subTest(name=bad), tempfile.TemporaryDirectory() as tmp:
                write_pack(tmp, "pack", palette_body(name=bad))
                with self.assertRaises(palette.ThemeError):
                    palette.catalog(Path(tmp))

    def test_descriptor_type_is_checked_after_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = write_pack(tmp, "pack") / "theme.toml"
            original_open = os.open

            def substitute_fifo(path, flags, *args, **kwargs):
                source.unlink()
                os.mkfifo(source)
                return original_open(path, flags, *args, **kwargs)

            with mock.patch.object(palette.os, "open", side_effect=substitute_fifo):
                with self.assertRaises(palette.ThemeError):
                    run_with_deadline(lambda: palette._read_bounded(source), seconds=0.5)

    def test_hyphens_and_digits_are_accepted_in_slugs(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "tokyo-night-2")
            self.assertEqual([theme.slug for theme in palette.catalog(Path(tmp))],
                             ["tokyo-night-2"])

    def test_directory_without_theme_toml_fails_the_whole_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "good")
            (Path(tmp) / "half-made").mkdir()
            with self.assertRaises(palette.ThemeError):
                palette.catalog(Path(tmp))

    def test_malformed_pack_fails_the_whole_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "good")
            write_pack(tmp, "broken", '[palette]\nbackground = "#000000"\n')
            with self.assertRaises(palette.ThemeError):
                palette.catalog(Path(tmp))

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            themes = Path(tmp) / "themes"
            themes.mkdir()
            outside = write_pack(tmp, "outside")
            (themes / "escape").symlink_to(outside)
            with self.assertRaises(palette.ThemeError):
                palette.catalog(themes)

    def test_theme_toml_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            themes = Path(tmp) / "themes"
            write_pack(themes, "pack")
            secret = Path(tmp) / "secret.toml"
            secret.write_text(palette_body())
            source = themes / "pack" / "theme.toml"
            source.unlink()
            source.symlink_to(secret)
            with self.assertRaises(palette.ThemeError):
                palette.catalog(themes)

    def test_oversized_pack_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "huge", palette_body() + "# " + "x" * 70_000 + "\n")
            with self.assertRaises(palette.ThemeError):
                palette.catalog(Path(tmp))

    def test_fifo_pack_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pipe"
            pack.mkdir()
            os.mkfifo(pack / "theme.toml")
            with self.assertRaises(palette.ThemeError):
                run_with_deadline(lambda: palette.catalog(Path(tmp)))

    def test_catalog_is_bounded_to_128_packs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(128):
                write_pack(tmp, "pack%03d" % index)
            self.assertEqual(len(palette.catalog(Path(tmp))), 128)
            write_pack(tmp, "pack128")
            with self.assertRaises(palette.ThemeError):
                palette.catalog(Path(tmp))


class CatalogWallpaperTest(unittest.TestCase):
    """The catalog carries each pack's wallpapers as path-free identities.

    A wallpaper is named by its filename, which the consumer sends back to
    `apply --background`, so the document must never leak where the pack lives.
    """

    def test_the_checkout_publishes_wallpaper_identities_per_pack(self):
        wallpapers = {theme.slug: apply_mod.wallpaper_ids(theme)
                      for theme in palette.catalog(ROOT / "themes")}
        self.assertEqual(sorted(wallpapers), list(SLUGS))
        self.assertEqual(wallpapers["catppuccin"],
                         ["1-totoro.webp", "2-waves.webp", "3-blue-eye.webp"])
        for slug, ids in wallpapers.items():
            for ident in ids:
                self.assertNotIn("/", ident, slug)
                self.assertNotIn("\\", ident, slug)
                self.assertFalse(ident.startswith("."), slug)

    def test_entries_stay_palette_only_while_the_document_gains_wallpapers(self):
        entries = [catalog_entry(theme) for theme in palette.catalog(ROOT / "themes")]
        for entry in entries:
            self.assertEqual(sorted(entry), sorted(ENTRY_FIELDS))
            self.assertNotIn("backgrounds", entry)
            self.assertNotIn("wallpapers", entry)

    def test_a_pack_without_backgrounds_publishes_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "bare")
            theme = palette.catalog(Path(tmp))[0]
            self.assertEqual(apply_mod.wallpaper_ids(theme), [])
            self.assertIsNone(apply_mod.wallpaper_path(theme, "1-a.webp"))

    def test_non_images_and_hidden_files_are_not_wallpapers(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_pack(tmp, "pack")
            write_backgrounds(folder, ["2-b.png", "1-a.webp", "notes.txt", ".hidden.webp"])
            theme = palette.catalog(Path(tmp))[0]
            self.assertEqual(apply_mod.wallpaper_ids(theme), ["1-a.webp", "2-b.png"])

    def test_a_name_that_could_address_a_directory_fails_the_catalog(self):
        # Both are legal filenames on APFS; neither can be published as an
        # identity that is later handed back as an argument.
        for bad in ("a\\b.webp", "tab\there.webp"):
            with self.subTest(name=bad), tempfile.TemporaryDirectory() as tmp:
                folder = write_pack(tmp, "pack")
                write_backgrounds(folder, [bad])
                with self.assertRaises(palette.ThemeError):
                    apply_mod.wallpaper_ids(palette.catalog(Path(tmp))[0])

    def test_oversized_wallpaper_names_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_pack(tmp, "pack")
            write_backgrounds(folder, ["a" * 130 + ".webp"])
            with self.assertRaises(palette.ThemeError):
                apply_mod.wallpaper_ids(palette.catalog(Path(tmp))[0])


class CatalogCliTest(unittest.TestCase):
    def test_cli_catalog_json_is_read_only_and_uses_the_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "only-pack", palette_body(name="Only Pack", accent="#123456"))
            result, sandbox = run_cli(themes=tmp)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["schema"], 1)
        self.assertEqual([entry["slug"] for entry in document["themes"]], ["only-pack"])
        entry = document["themes"][0]
        self.assertEqual(sorted(entry), sorted(ENTRY_FIELDS))
        self.assertEqual(entry["palette"]["accent"], "#123456")
        self.assertEqual(document["wallpapers"], {"only-pack": []})
        self.assertNotIn(tmp, result.stdout)
        self.assertFalse((sandbox / "state").exists())
        self.assertFalse((sandbox / "run").exists())

    def test_cli_catalog_publishes_wallpapers_without_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_pack(tmp, "only-pack")
            write_backgrounds(folder, ["2-b.webp", "1-a.jpg", "notes.txt"])
            result, sandbox = run_cli(themes=tmp)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["wallpapers"], {"only-pack": ["1-a.jpg", "2-b.webp"]})
        self.assertNotIn(tmp, result.stdout)

    def test_cli_catalog_refuses_an_unpublishable_wallpaper_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = write_pack(tmp, "only-pack")
            write_backgrounds(folder, ["bad\tname.webp"])
            result, sandbox = run_cli(themes=tmp)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mac-themer:", result.stderr)

    def test_cli_catalog_defaults_to_the_checkout(self):
        result, sandbox = run_cli(themes=None)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual([entry["slug"] for entry in document["themes"]], list(SLUGS))

    def test_cli_catalog_reports_an_empty_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, sandbox = run_cli(themes=tmp)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"schema": 1, "themes": [], "wallpapers": {}})

    def test_cli_catalog_fifo_does_not_hang(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pipe"
            pack.mkdir()
            os.mkfifo(pack / "theme.toml")
            result, sandbox = run_cli(themes=tmp, timeout=10)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mac-themer:", result.stderr)

    def test_cli_catalog_invalid_identity_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_pack(tmp, "BadName")
            result, sandbox = run_cli(themes=tmp)
        self.addCleanup(shutil.rmtree, str(sandbox), ignore_errors=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mac-themer:", result.stderr)


if __name__ == "__main__":
    unittest.main()

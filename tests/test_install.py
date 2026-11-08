#!/usr/bin/env python3
"""Importing a theme from a repository, and removing a pack again.

A repository is third-party content, so these tests pin the boundaries rather
than the happy path alone: which URLs are even offered to git, which files are
copied out of a checkout, what a failed import leaves behind, and which packs
`theme-uninstall` refuses to touch. Nothing here reaches the network: `git` is
a stub that copies a fixture tree, which is also how the clone's argument list
is pinned.

Run through tests/run.sh, which points MACTHEMER_* at a throwaway tree.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from macthemer import install, omarchy, palette, tokens  # noqa: E402

# A first-generation Omarchy palette: a named layer and an explicit ANSI ramp.
LEGACY = """
accent = "#cba6f7"
cursor = "#f5e0dc"
foreground = "#cdd6f4"
background = "#1e1e2e"
selection_foreground = "#cdd6f4"
selection_background = "#585b70"

color0 = "#45475a"
color1 = "#f38ba8"
color2 = "#a6e3a1"
color3 = "#f9e2af"
color4 = "#89b4fa"
color5 = "#f5c2e7"
color6 = "#94e2d5"
color7 = "#bac2de"
color8 = "#585b70"
color9 = "#f38ba8"
color10 = "#a6e3a1"
color11 = "#f9e2af"
color12 = "#89b4fa"
color13 = "#f5c2e7"
color14 = "#94e2d5"
color15 = "#a6adc8"
"""

# A palette stated only in semantic names, the shape the current reference
# documents. Everything else has to be derived the way it derives it.
SEMANTIC = """
mode = "light"

accent = "#7aa2f7"
selection = "#292e42"
muted = "#414868"

background = "#f2f2f2"
lighter_background = "#ffffff"
foreground = "#1a1b26"
dark_foreground = "#565f89"
bright_foreground = "#c0caf5"

red = "#f7768e"
yellow = "#e0af68"
green = "#9ece6a"
cyan = "#449dab"
blue = "#7aa2f7"
magenta = "#ad8ee6"
"""


def write_tree(root, files):
    """Write {relative path: text} under *root* and return it."""
    root = Path(root)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def stub_git(directory, body):
    """An executable that stands in for git; the clone's last argument is the
    destination, so a stub copies a fixture tree there."""
    path = Path(directory) / "git-stub"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def clone_stub(directory, source):
    return stub_git(
        directory,
        'for dest; do :; done\ncp -R "$MACTHEMER_TEST_TREE" "$dest"\n',
    ), str(source)


def theme_files(colors=LEGACY, backgrounds=("2-waves.webp", "1-totoro.webp")):
    files = {"colors.toml": colors}
    for name in backgrounds:
        files["backgrounds/" + name] = "image"
    return files


class RepoUrlTest(unittest.TestCase):
    def test_accepts_one_repository_over_https_only(self):
        for url, expected in [
            ("https://github.com/basecamp/omarchy", "https://github.com/basecamp/omarchy"),
            ("https://github.com/F1lmzy/omarchy-aura-theme.git",
             "https://github.com/F1lmzy/omarchy-aura-theme"),
            ("  https://github.com/a/b/  ", "https://github.com/a/b"),
            ("https://github.com/a-1/b_c.d", "https://github.com/a-1/b_c.d"),
        ]:
            self.assertEqual(install.parse_repo_url(url)[2], expected, url)
        self.assertEqual(install.parse_repo_url("https://github.com/a/b")[:2], ("a", "b"))

    def test_refuses_every_other_transport_and_shape(self):
        for url in [
            "",
            "   ",
            "github.com/a/b",
            "git@github.com:a/b.git",
            "http://github.com/a/b",
            "ssh://github.com/a/b",
            "git://github.com/a/b",
            "file:///tmp/themes",
            "ext::sh -c touch% /tmp/pwned",
            "https://user:token@github.com/a/b",
            "https://github.com:443/a/b",
            "https://gitlab.com/a/b",
            "https://github.com.evil/a/b",
            "https://github.com/a/b?ref=main",
            "https://github.com/a/b#main",
            "https://github.com/a",
            "https://github.com/a/b/tree/main",
            "https://github.com/a/%2e%2e",
            "https://github.com/a/..",
            "https://github.com/a/b\\c",
            "https://github.com/" + "a" * 200 + "/b",
        ]:
            with self.assertRaises(install.InstallError, msg=url):
                install.parse_repo_url(url)

    def test_a_pack_name_is_folded_into_the_slug_charset(self):
        self.assertEqual(install.slug_for("omarchy-aura-theme"), "aura")
        self.assertEqual(install.slug_for("Osaka.Jade"), "osaka-jade")
        self.assertEqual(install.slug_for("tokyo-night"), "tokyo-night")
        # An explicit name still has to be a pack name, not a path.
        self.assertEqual(install.slug_for("anything", "my_theme"), "my_theme")
        self.assertEqual(install.slug_for("anything", "My-Theme"), "my-theme")
        for bad in ("../escape", "a/b", "", "-lead", "a" * 129):
            with self.assertRaises(install.InstallError, msg=bad):
                install.slug_for("anything", bad)


class ColorsTest(unittest.TestCase):
    def test_a_legacy_palette_keeps_its_numbered_ramp(self):
        resolved, stated = omarchy.resolve({"colors": None, **self.table(LEGACY)})
        self.assertEqual(resolved["background"], "#1e1e2e")
        self.assertEqual(resolved["color0"], "#45475a", "the stated ANSI ramp won")
        self.assertEqual(resolved["color15"], "#a6adc8")
        self.assertEqual(resolved["lighter_background"], "#45475a")
        self.assertEqual(resolved["mode"], "dark")
        self.assertIn("background", stated)

    def test_a_semantic_palette_is_completed_by_the_documented_derivation(self):
        resolved, _ = omarchy.resolve(self.table(SEMANTIC))
        self.assertEqual(resolved["mode"], "light")
        self.assertEqual(resolved["color0"], "#f2f2f2", "color0 stands for background")
        self.assertEqual(resolved["color8"], "#414868", "color8 stands for muted")
        self.assertEqual(resolved["color15"], "#c0caf5")
        # A bright colour the theme does not state is mixed 20% toward white.
        self.assertEqual(resolved["color9"], palette.mix("#f7768e", "#ffffff", 0.2))
        self.assertEqual(resolved["cursor"], "#c0caf5", "no cursor key: bright foreground")
        self.assertEqual(resolved["selection"], "#292e42")

    def test_mode_falls_back_to_the_marker_then_to_luminance(self):
        table = {"background": "#ffffff", "foreground": "#000000",
                 "red": "#ff0000", "green": "#00ff00", "yellow": "#ffff00",
                 "blue": "#0000ff", "magenta": "#ff00ff", "cyan": "#00ffff"}
        self.assertEqual(omarchy.resolve(table)[0]["mode"], "light")
        self.assertEqual(omarchy.resolve(table, light_marker=True)[0]["mode"], "light")
        dark = dict(table, background="#000000")
        self.assertEqual(omarchy.resolve(dark)[0]["mode"], "dark")
        self.assertEqual(omarchy.resolve(dict(dark, theme_type="light"))[0]["mode"], "light")
        self.assertEqual(omarchy.resolve(dict(dark, mode="Light"))[0]["mode"], "light")

    def test_a_palette_without_a_colour_it_needs_is_refused_not_invented(self):
        with self.assertRaises(palette.ThemeError):
            omarchy.resolve({"background": "#101010", "foreground": "#eeeeee"})
        no_background = self.table(SEMANTIC)
        del no_background["background"]
        with self.assertRaises(palette.ThemeError):
            omarchy.resolve(no_background)

    def test_values_that_are_not_one_colour_are_dropped(self):
        table = self.table(LEGACY)
        table["hyprland_active_border"] = "rgba(33ccffee) rgba(00ff99ee) 45deg"
        table["accent"] = "not-a-colour"
        resolved, _ = omarchy.resolve(table)
        # A gradient cannot be a pack colour, and a broken accent falls back to
        # the scenario it stands in for rather than becoming one.
        self.assertEqual(resolved["accent"], "#89b4fa")

    def test_a_pack_pins_the_roles_the_theme_states(self):
        resolved, stated = omarchy.resolve(self.table(SEMANTIC))
        table = omarchy.pack(resolved, "demo", stated)
        self.assertEqual(table["variant"], "light")
        self.assertEqual(table["border"], {"active": "#7aa2f7", "inactive": "#ffffff"})
        self.assertEqual(table["tokens"], {"surface_container": "#ffffff",
                                           "on_surface_variant": "#565f89",
                                           "muted": "#414868"})
        self.assertEqual(set(table["palette"]), set(palette.PALETTE_KEYS))
        # A legacy palette states no semantic surface, so nothing is pinned.
        resolved, stated = omarchy.resolve(self.table(LEGACY))
        self.assertEqual(omarchy.pack(resolved, "demo", stated)["tokens"], {})

    def test_the_written_pack_is_what_the_catalog_reads(self):
        resolved, stated = omarchy.resolve(self.table(SEMANTIC))
        text = omarchy.document(omarchy.pack(resolved, "demo", stated),
                                source="https://github.com/a/b", version="9.9.9")
        self.assertIn("https://github.com/a/b", text)
        self.assertIn('variant = "light"', text)
        theme = palette.check(dict(self.parsed(text)), "demo/theme.toml", "demo")
        self.assertEqual(theme.slug, "demo")
        self.assertEqual(theme.palette["accent"], "#7aa2f7")
        self.assertEqual(tokens.tokens_for(theme)["primary"], "#7aa2f7")

    def parsed(self, text):
        import tomllib
        return tomllib.loads(text)

    def table(self, text):
        return self.parsed(text)


class Sandbox(unittest.TestCase):
    """One throwaway themes collection, state directory and stand-in git."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.themes = self.root / "themes"
        self.themes.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.patch = mock.patch.dict(os.environ, {
            "MACTHEMER_STATE": str(self.state),
            "MACTHEMER_RUN": str(self.root / "run"),
        })
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def serve(self, files, repo="omarchy-demo-theme"):
        """Point a stand-in git at a fixture tree and return the URL it serves."""
        tree = write_tree(self.work / repo, files)
        git = stub_git(self.work, 'for dest; do :; done\ncp -R "$MACTHEMER_TEST_TREE" "$dest"\n')
        patcher = mock.patch.dict(os.environ, {
            "MACTHEMER_GIT": str(git),
            "MACTHEMER_TEST_TREE": str(tree),
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        return "https://github.com/owner/" + repo

    def serve_failing(self):
        git = stub_git(self.work, "echo 'fatal: repository not found' >&2\nexit 128\n")
        patcher = mock.patch.dict(os.environ, {"MACTHEMER_GIT": str(git)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def leftovers(self):
        """Anything hidden left in the collection; staging must never linger."""
        return sorted(path.name for path in self.themes.iterdir()
                      if path.name.startswith("."))


class InstallTest(Sandbox):
    def test_install_imports_colors_and_backgrounds_only(self):
        url = self.serve({
            **theme_files(),
            "alacritty.toml": "this is another desktop's file",
            "waybar.css": "* { color: #fff }",
            "backgrounds/notes.txt": "not an image",
            "backgrounds/.DS_Store": "hidden",
            "hyprland.conf": "monitor = eDP-1",
        })
        result = install.install(url, directory=self.themes)
        self.assertEqual(result["packs"], [
            {"slug": "demo", "name": "Demo", "wallpapers": 2, "replaced": False}])
        pack = self.themes / "demo"
        self.assertEqual(sorted(path.name for path in pack.iterdir()),
                         [".source.json", "backgrounds", "theme.toml"])
        self.assertEqual(sorted(path.name for path in (pack / "backgrounds").iterdir()),
                         ["1-totoro.webp", "2-waves.webp"])
        # The pack is a pack as far as every reader is concerned.
        themes = palette.catalog(self.themes)
        self.assertEqual([theme.slug for theme in themes], ["demo"])
        self.assertEqual(themes[0].name, "Demo")
        self.assertFalse((self.state / "current.json").exists(),
                         "an import must not touch the active theme")
        record = json.loads((pack / ".source.json").read_text())
        self.assertEqual(record["format"], "omarchy")
        self.assertEqual(record["repo"], url)
        self.assertEqual(self.leftovers(), [], "staging was not cleaned up")

    def test_an_explicit_name_names_the_pack(self):
        url = self.serve(theme_files())
        result = install.install(url, slug="my_fonts", directory=self.themes)
        self.assertEqual(result["packs"][0]["slug"], "my_fonts")
        self.assertTrue((self.themes / "my_fonts" / "theme.toml").is_file())

    def test_a_collection_needs_all_and_each_theme_keeps_its_name(self):
        url = self.serve({
            "themes/aura/colors.toml": LEGACY,
            "themes/aura/backgrounds/1-a.webp": "image",
            "themes/jade/colors.toml": SEMANTIC,
        })
        with self.assertRaises(install.InstallError) as caught:
            install.install(url, directory=self.themes)
        self.assertIn("--all", str(caught.exception))
        self.assertEqual(self.leftovers(), [])
        result = install.install(url, all_themes=True, directory=self.themes)
        self.assertEqual([pack["slug"] for pack in result["packs"]], ["aura", "jade"])
        self.assertEqual([pack["wallpapers"] for pack in result["packs"]], [1, 0])
        self.assertEqual([theme.slug for theme in palette.catalog(self.themes)],
                         ["aura", "jade"])

    def test_reinstalling_replaces_only_what_this_command_installed(self):
        url = self.serve(theme_files())
        install.install(url, directory=self.themes)
        # A repository import may be refreshed by fetching it again.
        again = install.install(url, directory=self.themes)
        self.assertTrue(again["packs"][0]["replaced"])
        # A hand-written pack is not quietly eaten.
        hand = self.themes / "hand-made"
        write_tree(hand, {"theme.toml": (ROOT / "themes/tokyo-night/theme.toml").read_text()})
        url = self.serve(theme_files(), repo="omarchy-hand-made")
        with self.assertRaises(install.InstallError) as caught:
            install.install(url, directory=self.themes)
        self.assertIn("--force", str(caught.exception))
        self.assertTrue((hand / "theme.toml").is_file())
        forced = install.install(url, force=True, directory=self.themes)
        self.assertTrue(forced["packs"][0]["replaced"])
        self.assertEqual(palette.load(self.themes.parent, "hand-made").slug, "hand-made")

    def test_a_failed_import_leaves_no_pack_and_no_staging_directory(self):
        broken = write_tree(self.work / "broken", {"colors.toml": "this is not toml"})
        git = stub_git(self.work, 'for dest; do :; done\ncp -R "$MACTHEMER_TEST_TREE" "$dest"\n')
        with mock.patch.dict(os.environ, {"MACTHEMER_GIT": str(git),
                                          "MACTHEMER_TEST_TREE": str(broken)}):
            with self.assertRaises(install.InstallError):
                install.install("https://github.com/owner/omarchy-broken",
                                directory=self.themes)
        self.assertFalse((self.themes / "broken").exists())
        self.assertEqual(self.leftovers(), [])
        self.serve_failing()
        with self.assertRaises(install.InstallError) as caught:
            install.install("https://github.com/owner/gone", directory=self.themes)
        self.assertIn("could not fetch", str(caught.exception))
        self.assertEqual(self.leftovers(), [])

    def test_a_pack_that_breaks_a_published_bound_is_refused(self):
        url = self.serve(theme_files(backgrounds=("1-a.webp",)))
        # A background that is a symlink could point anywhere: refused, not
        # resolved.
        tree = Path(os.environ["MACTHEMER_TEST_TREE"])
        (tree / "backgrounds" / "2-link.webp").symlink_to(tree / "colors.toml")
        with self.assertRaises(install.InstallError) as caught:
            install.install(url, directory=self.themes)
        self.assertIn("regular file", str(caught.exception))
        self.assertEqual(self.leftovers(), [])

        too_many = {"colors.toml": LEGACY}
        for index in range(install.MAX_BACKGROUNDS + 1):
            too_many["backgrounds/%02d.webp" % index] = "image"
        url = self.serve(too_many, repo="omarchy-many")
        with self.assertRaises(install.InstallError) as caught:
            install.install(url, directory=self.themes)
        self.assertIn("more than", str(caught.exception))


class UninstallTest(Sandbox):
    def test_removing_a_pack_takes_it_out_of_the_catalog(self):
        url = self.serve(theme_files())
        install.install(url, directory=self.themes)
        self.assertEqual(install.uninstall("demo", directory=self.themes), {"slug": "demo"})
        self.assertFalse((self.themes / "demo").exists())
        self.assertEqual(palette.catalog(self.themes), [])
        self.assertEqual(self.leftovers(), [])

    def test_the_active_pack_named_a_path_or_a_missing_pack_is_refused(self):
        url = self.serve(theme_files())
        install.install(url, directory=self.themes)
        (self.state / "current").symlink_to(self.themes / "demo")
        with self.assertRaises(install.InstallError) as caught:
            install.uninstall("demo", directory=self.themes)
        self.assertIn("active theme", str(caught.exception))
        self.assertTrue((self.themes / "demo").is_dir())

        (self.state / "current").unlink()
        for slug in ("missing", "../demo", "/tmp", "", "Upper", "demo/child"):
            with self.assertRaises(install.InstallError, msg=slug):
                install.uninstall(slug, directory=self.themes)
        # A directory that is not a pack is somebody else's; leave it alone.
        (self.themes / "not-a-pack").mkdir()
        with self.assertRaises(install.InstallError):
            install.uninstall("not-a-pack", directory=self.themes)
        self.assertTrue((self.themes / "not-a-pack").is_dir())

    def test_removing_a_pack_forgets_a_background_that_lived_in_it(self):
        url = self.serve(theme_files())
        install.install(url, directory=self.themes)
        background = self.root / "run" / "background"
        background.parent.mkdir(parents=True)
        background.symlink_to(self.themes / "demo" / "backgrounds" / "1-totoro.webp")
        install.uninstall("demo", directory=self.themes)
        self.assertFalse(background.is_symlink())


class InstallCliTest(Sandbox):
    """The commands a service drives, end to end, on a throwaway tree."""

    def run_cli(self, *args):
        env = dict(os.environ, MACTHEMER_REPO=str(ROOT),
                   MACTHEMER_THEMES=str(self.themes), MACTHEMER_DRY_RUN="1")
        return subprocess.run([sys.executable, str(ROOT / "bin" / "mac-themer"), *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def test_cli_installs_and_removes_a_pack(self):
        url = self.serve(theme_files())
        installed = self.run_cli("theme-install", url, "--json")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(json.loads(installed.stdout), {
            "schema": 1, "status": "installed",
            "packs": [{"slug": "demo", "name": "Demo", "wallpapers": 2, "replaced": False}],
        })
        self.assertNotIn(str(self.root), installed.stdout)

        catalog = json.loads(self.run_cli("catalog", "--json").stdout)
        self.assertEqual([entry["slug"] for entry in catalog["themes"]], ["demo"])
        self.assertEqual(catalog["wallpapers"], {"demo": ["1-totoro.webp", "2-waves.webp"]})

        removed = self.run_cli("theme-uninstall", "demo", "--json")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(json.loads(removed.stdout),
                         {"schema": 1, "status": "removed", "slug": "demo"})
        self.assertEqual(json.loads(self.run_cli("catalog", "--json").stdout)["themes"], [])

    def test_cli_refuses_a_url_that_is_not_one_github_repository(self):
        for url in ("http://github.com/a/b", "git@github.com:a/b.git",
                    "https://example.com/a/b"):
            result = self.run_cli("theme-install", url, "--json")
            self.assertNotEqual(result.returncode, 0, url)
            self.assertIn("mac-themer:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(palette.catalog(self.themes), [])


if __name__ == "__main__":
    unittest.main()

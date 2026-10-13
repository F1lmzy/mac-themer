"""Where mac-themer keeps things, overridable for tests.

Every path is a function, not a constant: the CLI resolves them once at
startup, and the test suite points them at a temporary directory so a test
run never touches the real desktop.
"""
from __future__ import annotations

import os
from pathlib import Path


def _env_path(name, default):
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def repo_root():
    """The checkout this module was imported from, unless overridden."""
    override = os.environ.get("MACTHEMER_REPO")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2]


def home():
    return Path(os.environ.get("MACTHEMER_HOME") or Path.home())


def state_dir():
    """Canonical mac-themer state: resolved palette, current symlink, config."""
    return _env_path("MACTHEMER_STATE", home() / ".config" / "macthemer")


def compat_dir():
    """The omarchy-convention directory every existing consumer already reads.

    Kept publishing here so a mixed machine (mac-themer themes, an
    omacosy bar or helper still running) does not go unstyled during the
    move. Retire it once nothing on the machine reads it.
    """
    return _env_path("MACTHEMER_COMPAT", home() / ".config" / "omarchy" / "current")


def run_dir():
    """mac-themer's own mutable state: the remembered background, pids."""
    return _env_path("MACTHEMER_RUN", home() / ".local" / "state" / "macthemer")


def legacy_run_dir():
    """omacosy's state dir, still written for its helper's wallpaper resync."""
    return _env_path("MACTHEMER_LEGACY_RUN", home() / ".local" / "state" / "omacosy")


def bin_dir():
    return _env_path("MACTHEMER_BIN", home() / ".local" / "bin")


def agents_dir():
    return _env_path("MACTHEMER_AGENTS", home() / "Library" / "LaunchAgents")


def config_file():
    return state_dir() / "config.toml"


def borders_conf():
    return state_dir() / "borders.conf"


def current_link():
    return state_dir() / "current"


def resolved_file():
    return state_dir() / "current.json"

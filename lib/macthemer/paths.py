"""Where mac-themer keeps things, overridable for tests.

Every path is a function, not a constant: the CLI resolves them once at
startup, and the test suite points them at a temporary directory so a test run
never touches the real desktop.
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
    """The one place mac-themer publishes state: fragment, palette, config."""
    return _env_path("MACTHEMER_STATE", home() / ".config" / "macthemer")


def run_dir():
    """mac-themer's own mutable state: the remembered background, pids."""
    return _env_path("MACTHEMER_RUN", home() / ".local" / "state" / "macthemer")


def bin_dir():
    return _env_path("MACTHEMER_BIN", home() / ".local" / "bin")


def agents_dir():
    return _env_path("MACTHEMER_AGENTS", home() / "Library" / "LaunchAgents")


def borders_conf():
    return state_dir() / "borders.conf"


def current_link():
    return state_dir() / "current"


def resolved_file():
    return state_dir() / "current.json"


def ghostty_fragment():
    """The palette fragment Ghostty is told to load by config-file.

    It lives in the state directory rather than beside the pack because it is
    the path written into the user's Ghostty config: a stable location means a
    theme switch never has to rewrite that config.
    """
    return state_dir() / "ghostty.conf"


def backgrounds_link():
    return run_dir() / "background"

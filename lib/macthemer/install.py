"""Install and remove theme packs fetched from a GitHub repository.

An Omarchy theme repository is a directory of colours and pictures plus a pile
of per-application files that desktop generates for itself. Only two of those
things are a palette and a wallpaper list, so installation keeps exactly
`colors.toml` and `backgrounds/` and drops the rest: nothing from a third-party
repository is executed, sourced, or copied into a pack because it looked
important.

The fetched URL is the one piece of third-party input that becomes an argument,
so it is held to `https://github.com/<owner>/<repo>` with a narrow character
set, and git is told to speak no other transport. A clone lands in a hidden
staging directory inside the themes collection, is validated by the same rules
the catalog applies, and only becomes visible in one rename.

Everything here reports by returning data; nothing prints.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
import urllib.parse
from pathlib import Path

from . import __version__, omarchy, palette, paths
from .apply import IMAGE_SUFFIXES

# A repository URL crosses a process boundary and becomes an argument.
MAX_URL_BYTES = 512
# What one pack may carry. The same ceiling the catalog and its consumers hold
# to, so an imported pack can never publish a list they would refuse.
MAX_BACKGROUNDS = 64
MAX_BACKGROUND_BYTES = 16 * 1024 * 1024
MAX_BACKGROUNDS_BYTES = 64 * 1024 * 1024
MAX_MARKER_BYTES = 8192
# One `git clone` deadline. A theme repository is small; a clone that has not
# finished by then is not going to.
CLONE_TIMEOUT = 180

GITHUB_HOST = "github.com"
# One path segment of a GitHub owner or repository name. Deliberately narrower
# than GitHub allows: this name is joined into a URL and then names a pack
# directory, so it must not be able to name a path, an option or a transport.
SEGMENT = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")

# Written inside an imported pack so a later install can tell a pack this
# command made from one a human wrote. Hidden: the catalog reads theme.toml and
# nothing else, and this is not part of a pack's published identity.
SOURCE_MARKER = ".source.json"
MARKER_SCHEMA = 1


class InstallError(palette.ThemeError):
    """A repository cannot be turned into a pack."""


def parse_repo_url(url):
    """Validate a repository URL and return `(owner, repo, canonical)`.

    Only `https://github.com/<owner>/<repo>` is accepted. No other scheme, host,
    port, credentials, query, fragment or path depth: a caller that could name
    a transport helper or a local path here could make git do something that is
    not a clone, and that decision is taken before git ever runs.
    """
    if not isinstance(url, str):
        raise InstallError("repository URL must be a string")
    text = url.strip()
    if not text or len(text.encode("utf-8")) > MAX_URL_BYTES:
        raise InstallError("repository URL must be 1-%d bytes" % MAX_URL_BYTES)
    if "%" in text or "\\" in text or "\x00" in text:
        raise InstallError("repository URL must not carry escapes")
    if "://" not in text:
        raise InstallError(
            "use an https://%s/<owner>/<repo> repository URL" % GITHUB_HOST)
    parsed = urllib.parse.urlsplit(text)
    if parsed.scheme != "https":
        raise InstallError("only https:// repository URLs are supported")
    if parsed.hostname != GITHUB_HOST or parsed.port is not None:
        raise InstallError("only %s repositories are supported" % GITHUB_HOST)
    if parsed.username is not None or parsed.password is not None:
        raise InstallError("repository URL must not carry credentials")
    if parsed.query or parsed.fragment:
        raise InstallError("repository URL must not carry a query or fragment")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) != 2:
        raise InstallError(
            "repository URL must name one repository: https://%s/<owner>/<repo>"
            % GITHUB_HOST)
    owner, repo = segments
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    if not SEGMENT.match(owner) or not SEGMENT.match(repo):
        raise InstallError("repository URL names an unusable %s path" % GITHUB_HOST)
    return owner, repo, "https://%s/%s/%s" % (GITHUB_HOST, owner, repo)


def slug_for(repo, override=None):
    """The pack name a repository installs as.

    A repository is named for a desktop that is not this one, so the prefix and
    suffix those names carry are dropped and the rest is folded into the pack
    slug charset. Unusable characters become separators instead of refusing an
    otherwise fine theme; a name that folds away to nothing is refused.
    """
    if override is not None:
        candidate = override.strip().lower()
        if not palette.SLUG.match(candidate):
            raise InstallError(
                "%r is not a pack name: lowercase letters, digits, - and _ only"
                % override)
        return candidate
    name = repo.strip().lower()
    if name.startswith("omarchy-"):
        name = name[len("omarchy-"):]
    if name.endswith("-theme"):
        name = name[: -len("-theme")]
    name = re.sub(r"[^a-z0-9_-]+", "-", name).strip("-_")
    if not palette.SLUG.match(name):
        raise InstallError("%r does not give a usable pack name; pass --slug" % repo)
    return name


def marker(pack_dir):
    """The import record of a pack, or None when a human wrote it."""
    path = Path(pack_dir) / SOURCE_MARKER
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        if os.lstat(path).st_size > MAX_MARKER_BYTES:
            return None
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema") != MARKER_SCHEMA:
        return None
    return record


def images(folder):
    """The wallpapers in *folder*, sorted.

    Hidden entries are skipped and a name that could address another directory
    is refused, because the identity is published and then handed back as an
    argument. The count and the byte budget are what keeps one repository from
    turning a catalog entry into a file browser.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    found = []
    total = 0
    for path in sorted(folder.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".") or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.is_symlink() or not path.is_file():
            raise InstallError("backgrounds/%s is not a regular file" % path.name)
        if len(path.name.encode("utf-8")) > 128:
            raise InstallError("backgrounds/%s has an unusable name" % path.name)
        size = path.stat().st_size
        if size > MAX_BACKGROUND_BYTES:
            raise InstallError("backgrounds/%s is larger than %d bytes"
                               % (path.name, MAX_BACKGROUND_BYTES))
        total += size
        if total > MAX_BACKGROUNDS_BYTES:
            raise InstallError("backgrounds/ is larger than %d bytes"
                               % MAX_BACKGROUNDS_BYTES)
        found.append(path)
        if len(found) > MAX_BACKGROUNDS:
            raise InstallError("backgrounds/ holds more than %d images" % MAX_BACKGROUNDS)
    return found


def _git():
    return os.environ.get("MACTHEMER_GIT") or "git"


def clone(url, destination):
    """Clone *url* into *destination* with every transport but https refused."""
    command = [
        _git(),
        # Only https may be spoken, whatever a user's git config says a URL
        # should be rewritten to, and a redirect may not move the clone.
        "-c", "protocol.allow=never",
        "-c", "protocol.https.allow=always",
        "-c", "http.followRedirects=false",
        "clone", "--depth", "1", "--single-branch", "--no-tags", "--quiet",
        "--", url, str(destination),
    ]
    environment = dict(os.environ)
    # No credential prompt: this runs from a daemon, and a theme repository is
    # public or it is not installable. LFS stays a pointer, because the smudge
    # filter is a program the repository chose.
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GIT_LFS_SKIP_SMUDGE"] = "1"
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=CLONE_TIMEOUT, env=environment)
    except FileNotFoundError:
        raise InstallError("git is not installed")
    except subprocess.TimeoutExpired:
        raise InstallError("fetching %s took longer than %ds" % (url, CLONE_TIMEOUT))
    if result.returncode != 0:
        detail = [line.strip() for line in (result.stderr or "").splitlines() if line.strip()]
        raise InstallError("could not fetch %s: %s"
                           % (url, detail[-1] if detail else "git failed"))


def build(checkout, staged, slug, name=None, origin=None):
    """Turn one directory of a checkout into a completed, validated pack.

    Returns the pack's public summary. The pack is already checked by the same
    rules `catalog` applies, so the caller only has to move it into place.
    """
    directory = Path(checkout)
    try:
        resolved, stated = omarchy.read(directory)
        table = omarchy.pack(resolved, slug, stated, name=name)
        text = omarchy.document(table, source=origin, version=__version__)
        # Validate the document that will be written, not the table it came
        # from: a serializer that drops a key would otherwise publish a broken
        # pack that fails the whole catalog later.
        palette.check(tomllib.loads(text), Path(slug) / "theme.toml", slug)
    except (palette.ThemeError, tomllib.TOMLDecodeError) as exc:
        raise InstallError("%s: %s" % (slug, exc))
    pictures = images(directory / "backgrounds")
    staged = Path(staged)
    staged.mkdir(parents=True, exist_ok=False)
    (staged / "theme.toml").write_text(text)
    if pictures:
        (staged / "backgrounds").mkdir()
        for picture in pictures:
            shutil.copyfile(picture, staged / "backgrounds" / picture.name)
    record = {
        "schema": MARKER_SCHEMA,
        "format": "omarchy",
        "repo": origin or "",
        "installed_by": "mac-themer %s" % __version__,
    }
    (staged / SOURCE_MARKER).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n")
    return {"slug": slug, "name": table["name"], "wallpapers": len(pictures)}


def themes_root(directory=None):
    root = Path(directory or paths.themes_dir())
    if not root.is_dir():
        raise InstallError("no themes collection at %s" % root)
    return root


def install(url, slug=None, all_themes=False, force=False, directory=None):
    """Install one repository's theme, or every theme it states.

    Returns `{"packs": [summary, ...]}`; each summary carries the slug that was
    installed, the display name, how many wallpapers came with it and whether
    it replaced an older copy. An existing pack is replaced when this command
    installed it, and only with `force` when a human wrote it: an import must
    not quietly eat a hand-tuned palette.
    """
    if all_themes and slug is not None:
        raise InstallError("--all installs every theme; it cannot take --slug")
    _, repo, canonical = parse_repo_url(url)
    root = themes_root(directory)
    staging = Path(tempfile.mkdtemp(prefix=".install-", dir=root))
    try:
        checkout = staging / "repo"
        clone(canonical, checkout)
        found = omarchy.candidates(checkout)
        if not found:
            raise InstallError("%s publishes no colors.toml" % canonical)
        if len(found) > 1 and not all_themes:
            names = ", ".join(path.name for path in found)
            raise InstallError(
                "%s holds %d themes (%s); install them all with --all"
                % (canonical, len(found), names))
        slugs = [slug_for(repo, slug)] if len(found) == 1 else [
            slug_for(path.name) for path in found]
        if len(set(slugs)) != len(slugs):
            raise InstallError("%s has two themes that install as one pack" % canonical)
        packs = []
        for directory_path, name in zip(found, slugs):
            built = staging / ("pack-%s" % name)
            try:
                summary = build(directory_path, built, name, origin=canonical)
                summary["replaced"] = _commit(root, built, name, force, staging)
            except InstallError as exc:
                # A batch is not a transaction: say which packs are already
                # installed instead of implying nothing happened.
                if not packs:
                    raise
                raise InstallError(
                    "%s (already installed: %s)"
                    % (exc, ", ".join(pack["slug"] for pack in packs)))
            packs.append(summary)
        return {"packs": packs}
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _commit(root, staged, slug, force, staging):
    """Move a validated pack into the collection. Returns whether it replaced one."""
    target = root / slug
    if target.is_symlink() or target.exists():
        if target.is_symlink() or not target.is_dir() or not (target / "theme.toml").is_file():
            raise InstallError("%s exists and is not a pack" % target)
        if marker(target) is None and not force:
            raise InstallError(
                "%s is a pack this command did not install; pass --force to replace it"
                % slug)
        backup = staging / ("replaced-%s" % slug)
        os.replace(target, backup)
        replaced = True
    else:
        backup, replaced = None, False
    try:
        os.replace(staged, target)
    except OSError:
        if backup is not None:
            os.replace(backup, target)
        raise
    if backup is not None:
        shutil.rmtree(backup, ignore_errors=True)
    return replaced


def uninstall(slug, directory=None):
    """Remove one pack from the collection, and report what went.

    Refuses the active pack: the current-theme link points at that directory,
    and removing it would leave the desktop pointing at nothing. Refuses
    anything that is not a pack inside the collection, so a hand-typed name
    cannot become a path.
    """
    if not isinstance(slug, str) or not palette.SLUG.match(slug):
        raise InstallError("%r is not a pack name" % (slug,))
    root = themes_root(directory).resolve()
    target = root / slug
    if target.is_symlink() or not target.is_dir():
        raise InstallError("no pack %r in %s" % (slug, root))
    if not (target / "theme.toml").is_file():
        raise InstallError("%s is not a pack" % slug)
    if target.resolve() != target:
        raise InstallError("%s leaves the themes collection" % slug)
    link = paths.current_link()
    if link.is_symlink() and Path(os.readlink(link)).resolve() == target:
        raise InstallError("%s is the active theme; set another pack first" % slug)
    # A hidden name is not a pack to the catalog, so the pack leaves the
    # published list in one rename and only then is deleted.
    removed = Path(tempfile.mkdtemp(prefix=".removed-", dir=root)) / slug
    os.replace(target, removed)
    background = paths.backgrounds_link()
    if background.is_symlink():
        try:
            inside = target in Path(os.readlink(background)).resolve().parents
        except OSError:
            inside = False
        if inside:
            background.unlink()
    shutil.rmtree(removed.parent, ignore_errors=True)
    return {"slug": slug}

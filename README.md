# mac-themer

Theme packs, the palette fan-out and the focused-window border ring for a
macOS desktop rice.

One pack decides every colour on the desktop. `mac-themer set <pack>` renders
each consumer's own format from it, points the apps that are running at the new
values, and writes one machine-readable palette that anything newer can read
instead of parsing shell.

mac-themer is standalone. It installs, runs and uninstalls on its own: no other
project's helper, directory or updater is read, written or reinstalled, and
`tests/test_render.py::OwnnessTest` fails the suite if that ever stops being
true. The theming and border layer was ported out of another rice and now lives
here; the port's provenance is in [NOTICE.md](NOTICE.md).

## Install

```sh
./install.sh          # builds the ring + wallpaper helper, links the CLI, applies a pack
./tests/run.sh        # unit, golden and CLI tests, all in a sandbox
./uninstall.sh        # removes the ring, the binaries and the links
```

Requires macOS 26, the Xcode command line tools (`swiftc`) and python3 3.11+
(`tomllib`). Nothing needs Full Disk Access or Accessibility: the ring needs no
permissions at all.

## Use

```sh
mac-themer list                 # packs, with the active one marked
mac-themer set gruvbox          # apply
mac-themer next                 # cycle
mac-themer bg-next              # next wallpaper in the pack
mac-themer bg-next ~/pic.jpg    # or set one exactly
mac-themer wallpaper gruvbox --id 1-the-backwater.jpg --json   # one pack wallpaper, no theme change
mac-themer dump                 # every resolved colour, or --json
mac-themer catalog --json       # every pack's resolved palette, for a picker
mac-themer apply gruvbox \
  --expected-palette "$ENTRY" --json   # apply one pack after a full palette check
mac-themer apply gruvbox \
  --expected-palette "$ENTRY" --background 1-the-backwater.jpg --json   # and its wallpaper
mac-themer current --json       # the resolved palette as an app would read it
mac-themer doctor               # state, other ring daemons, what is installed where
```

`theme-set`, `theme-next` and `theme-bg-next` still exist and do the same
things. They are kept as names because chords and keybindings already call them,
so nothing has to be rewritten to move over. `theme-set` with no argument lists
packs.

`mac-themer catalog --json` is the read-only counterpart for a consumer that
builds a picker: it returns `{schema, themes, wallpapers}` with every pack's
resolved palette, without consulting the active theme and without machine
paths. Each entry carries the same resolved colours `current --json` does,
minus the three keys (`generated_by`, `pack`, `backgrounds`) that describe
where a pack lives. The separate `wallpapers` map names each pack's images by
filename (`{"gruvbox": ["1-the-backwater.jpg", ...]}`), sorted in the order
`set` and `bg-next` cycle them; a filename is an identity, never a path.
`MACTHEMER_THEMES` points it at another collection of packs; a broken pack
fails the whole call instead of returning a partial list.

`mac-themer apply <slug> --expected-palette JSON --json` is the write side of
that same contract. `JSON` is one `themes[]` entry from `catalog --json`. The
command reloads the catalog, selects the exact ASCII slug, and compares the
pack's full resolved palette, `tokens`, `border` and `bar` included, with the
document it was handed. A different colour, an added or missing field, or a
non-integer `alpha_byte` is refused before any file is written. On success it
applies that pack with `wallpaper=false` and prints
`{schema, status: "applied", theme, wallpaper, warnings}`; a Ghostty reload that
failed becomes the `ghosttyReloadFailed` warning instead of a silent success.
The expected palette, not the slug, is the authorization: a caller can never
name a path.

`--background ID` additionally sets one of that pack's own images, named exactly
as `catalog --json` published it. The response then carries the wallpaper it
set, or `null` plus a `wallpaperFailed` warning when neither the helper nor the
AppleScript fallback could change it — the palette apply still stands. Without
the flag the wallpaper is never touched, which is why `wallpaper` is `null` and
an older consumer keeps its exact previous behaviour. `set`/`next` are
unchanged and still take only a slug.

A separate shared launcher service drives this command for a confirmed Apply;
the producer side stays a plain CLI that any caller can use.

`mac-themer wallpaper SLUG --id ID --json` sets one of that pack's wallpapers on
its own: it validates the identity against the pack, moves the remembered
background and prints `{schema, status, theme, wallpaper, warnings}`. It writes
no theme file, rewrites no app setting and does not touch the active theme, so
it is the command a wallpaper picker uses. `status` is `failed` with a
`wallpaperFailed` warning when neither the helper nor the AppleScript fallback
could change the picture.

## Importing a theme

A theme published for Omarchy is one `colors.toml` of named colours, an
optional `backgrounds/` folder and per-application files that desktop generates
for itself. mac-themer imports the first two and nothing else:

```sh
mac-themer theme-install https://github.com/owner/omarchy-aura-theme
mac-themer theme-install https://github.com/owner/themes-repo --all   # a collection
mac-themer theme-install https://github.com/owner/omarchy-aura-theme --json
mac-themer theme-uninstall aura
```

The repository is cloned shallowly into a hidden staging directory inside the
themes collection, `colors.toml` is translated into a pack's `theme.toml`, the
images in `backgrounds/` are copied, and the result is validated by the same
rules `catalog` applies before it becomes visible in one rename. Nothing else
from the repository is copied: no `hyprland.conf`, no `waybar.css`, no
`alacritty.toml`, nothing executable, and no script is ever run.

What the pack keeps:

- every colour the theme states, in the source's own precedence: a canonical
  name over its legacy alias (`foreground` over `fg`) and over the numbered
  ANSI entry it stands for (`color7`), and a stated numbered entry over both,
  because a theme that writes a terminal ramp had its terminal already showing
  it. A colour the theme leaves out is derived the way that format derives it,
  and a palette missing a colour a pack needs is refused rather than invented;
- the variant, from `mode`, then the legacy `theme_type`, then a `light.mode`
  marker, then the background's luminance;
- a border ring on the theme's own focus colour and its raised surface, and the
  three semantic roles it states (`surface_container`, `on_surface_variant`,
  `muted`). Every other role is still derived by `lib/macthemer/tokens.py`.

Which URLs are allowed is decided before git runs: `https://github.com/<owner>/<repo>`,
one repository, no other host, scheme, port, credentials, query, fragment or
path depth. The clone additionally refuses every transport but https and will
not follow a redirect, so a rewritten URL cannot turn a clone into something
else. `--slug` names the pack instead of deriving it from the repo name;
`--force` is needed to replace a pack this command did not install, so an
import never silently eats a hand-tuned palette. `theme-uninstall` refuses the
active pack and anything that is not a pack inside the collection. An imported
pack is a pack like the bundled four: `mac-themer set <slug>` applies it, and
`catalog --json` lists it.

The five limits are what keep one repository from becoming a catalog entry that
consumers refuse: 64 wallpapers, 16 MiB per image, 64 MiB of images, a
128-byte wallpaper filename, and one theme's worth of `colors.toml`. A
repository holding several themes installs only with `--all`, so a collection
never quietly becomes one pack. An imported pack is an ordinary untracked
directory under the collection `catalog` reads (`.gitignore` covers the two
files mac-themer renders next to `theme.toml`), marked with a `.source.json`
that records the repository it came from.

## The palette model

A pack is one file. `themes/<slug>/theme.toml` carries a base16/ANSI palette
because that is what terminals need, explicit border colours because whether the
inactive ring should be a raised surface or the palette's dimmest tone is a
judgement call about that palette, and overrides for any semantic role the
derivation gets wrong:

```toml
name = "Catppuccin Mocha"
variant = "dark"

[palette]                 # background, foreground, cursor, accent,
background = "#1e1e2e"    # selection_background, selection_foreground,
foreground = "#cdd6f4"    # color0..color15
# ...

[border]
active = "#cba6f7"
inactive = "#45475a"

[tokens]                  # overrides on the derived roles
surface_container = "#313244"
muted = "#6c7086"

[bar]
background_alpha = 0.902
```

`lib/macthemer/tokens.py` derives the roles anything with a UI needs — surface,
on-surface, the elevation ramp, primary, outline, muted, error/success/warning —
from that palette, in sRGB (the space the palette was picked in, not linear
light). A pack that disagrees pins the role and nothing else changes. The bar's
red/green/yellow come from the *bright* ANSI ramp by default: a bar is small and
read at a glance, while the normal ramp is tuned for text on the terminal
background.

`lib/macthemer/render.py` turns one resolved pack into every format. Each
renderer is a pure function, which is what lets `tests/golden/` hold the exact
bytes.

## What gets written

In the pack directory (`themes/<slug>/`, gitignored, because the active-theme
pointer is a symlink to the pack and a consumer resolving it reads these next to
it):

| File | Read by |
|---|---|
| `colors.toml` | anything that only wants a base16 palette, including a human |
| `ghostty.conf` | Ghostty, when the pack is applied |

In the state directory (`~/.config/macthemer/`):

| Path | What it is |
|---|---|
| `current` | symlink to the active pack |
| `current.json` | the resolved palette: palette, tokens, border, bar, alpha |
| `ghostty.conf` | the fragment Ghostty is told to load |
| `borders.conf` | ring geometry (width, gap, radius, per-app radius) |

`current.json` is the interface for everything that is not wired yet. It is
written atomically and carries the palette, the semantic roles and the named
border and bar colours, so an app needs no theme logic of its own and no shell
parsing:

```json
{
  "schema": 1,
  "slug": "catppuccin",
  "name": "Catppuccin Mocha",
  "pack": "themes/catppuccin",
  "backgrounds": "themes/catppuccin/backgrounds",
  "alpha_byte": 230,
  "palette": { "background": "#1e1e2e", "color15": "#a6adc8", "...": "..." },
  "tokens": { "surface": "#1e1e2e", "primary": "#cba6f7", "...": "..." },
  "border": { "active": "#cba6f7", "inactive": "#45475a" },
  "bar": { "background": "#1e1e2e", "red": "#f38ba8", "...": "..." }
}
```

Paths in it are relative on purpose: a published artifact must not carry this
machine's layout.

There is no shell-fragment output. A palette is data, and a consumer that wants
it can read `current.json`; generating `.sh` files to be `source`d meant
publishing files into a directory another project owns, which is exactly the
coupling this repo dropped.

## The border ring

`borders/borders.swift` draws a ring around the focused window. It is a port of
another project's daemon and keeps that revision's behaviour, including the parts
that exist only because of something the window server actually does: SkyLight
notifications instead of polling, the frontmost-pid lookup that skips AppKit's
~1s focus lag, per-window move/resize subscriptions, and wall-clock deferral gates
so a transient miss does not blink the ring. It needs no permissions.

What the port changed:

- geometry comes from `~/.config/macthemer/borders.conf` and the ring colour from
  `current.json`, both watched with kqueue and re-read in place. A truncated file
  fails the parse and keeps the last colour, rather than matching a line by luck;
- it watches `/tmp/macthemer-ws-switch`, its own sentinel, and nothing else;
- **it covers AeroSpace only.** Under OmniWM the ring parks itself and OmniWM
  draws its own border. mac-themer does not write into OmniWM's settings.

`width`, `gap` and `radius` are a concentric set: the ring radius is the window's
corner radius plus `gap` plus half `width`. Change `gap` and move the radii with
it, or the ring fights the window's own corners. The conf file documents the
measured radii for the apps that were measured.

## Wallpapers

`helper/wallpaper.swift` is built by `install.sh` as `macthemer-wallpaper`:

```sh
macthemer-wallpaper set <path>      # every screen
macthemer-wallpaper get             # one line per screen
macthemer-wallpaper resync <path>   # re-assert it on screens showing something else
```

NSWorkspace is used directly because it is the only path that reliably sets a
per-screen picture on macOS 14 and later: System Events wallpaper scripting
intermittently returns `missing value` there and silently keeps the old image.
`resync` exists because macOS keeps the desktop picture per display, so a screen
unplugged during a theme change comes back showing the theme before it. Applying
a pack falls back to System Events when the helper has not been built yet.

## Tests

```sh
./tests/run.sh                        # unit, golden, CLI sandbox
MACTHEMER_TEST_BUILD=1 ./tests/run.sh # also compile the two Swift binaries
./tests/update-goldens.sh             # rewrite goldens after a renderer change
```

The suite never touches the real desktop: the CLI tests copy the checkout, point
every `MACTHEMER_*` path at a temporary tree and set `MACTHEMER_DRY_RUN=1`, so
applying a theme moves a symlink in `/tmp` instead of taking over the tester's
wallpaper, Ghostty window and Korren config.

Two suites are the point of the file. `RegressionPinTest` pins the bar and border
colours for all four packs, read off the machine before the theming moved, so a
change to the derivation that would restyle the desktop fails there instead of
being noticed weeks later. `OwnnessTest` scans the code for another project's
name and fails on any reference outside a comment, which is what keeps this repo
from quietly growing a dependency back.

## Not in this slice

- The Qt pill and `maccer` are not wired to `current.json` yet. The launcher's
  `crates/launcher-ui/src/theme.rs` is still hardcoded greyscale and the pill's
  `Theme.qml` is still its own washi palette; both are meant to read the resolved
  palette and keep their own identity as a named pack.
- OmniWM's border colour is OmniWM's business here. If that changes, it becomes
  another renderer, not more logic in the CLI.
- Wallpaper-to-palette generation is not implemented. The pill carries a
  `Dyn`/matugen path that could feed it back in as a generated pack.
- Imports read colours and pictures only. A theme's own per-application files
  are not translated, and nothing outside `colors.toml` can change a pack.

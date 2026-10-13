# mac-themer

Theme packs, the palette fan-out and the focused-window border ring for a
macOS desktop rice.

One pack decides every colour on the desktop. `mac-themer set <pack>` renders
each consumer's own format from it, points the apps that are running at the new
values, and writes one machine-readable palette that anything newer can read
instead of parsing shell. This is the theming and border layer lifted out of
[omacosy](https://github.com/paulsp94/omacosy) and owned here, so the rest of
the desktop can move off that project without losing its look.

## Install

```sh
./install.sh          # builds the border ring, links the CLI, applies a pack
./tests/run.sh        # 30 unit tests, goldens, and a CLI run in a sandbox
./uninstall.sh        # removes the ring and the links; --purge-state for state
```

Requires macOS 26, the Xcode command line tools (`swiftc`) and python3 3.11+
(`tomllib`). Nothing needs Full Disk Access or Accessibility: the ring needs no
permissions at all.

`install.sh` stops `com.omacosy.borders` if it is loaded, because two ring
daemons draw two rings. `uninstall.sh` gives that agent back.

## Use

```sh
mac-themer list                 # packs, with the active one marked
mac-themer set gruvbox          # apply
mac-themer next                 # cycle
mac-themer bg-next              # next wallpaper in the pack
mac-themer bg-next ~/pic.jpg    # or set one exactly
mac-themer dump                 # every resolved colour, or --json
mac-themer current --json       # the resolved palette as an app would read it
mac-themer doctor               # state, conflicts, what is installed where
```

`theme-set`, `theme-next` and `theme-bg-next` still exist and do the same
things. They are kept as names because AeroSpace chords, the omacosy bar and
the Qt pill already shell out to them, so nothing has to be rewritten to move
over. `theme-set` with no argument lists packs, which is what it did before.

## The palette model

A pack is one file. `themes/<slug>/theme.toml` carries a base16/ANSI palette
because that is what terminals need, explicit border colours because whether
the inactive ring should be a raised surface or the palette's dimmest tone is a
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

Generated next to the pack in `themes/<slug>/` (gitignored, because the active
pointer is a symlink to the pack directory and consumers resolve it and read
the file next to it):

| File | Read by |
|---|---|
| `colors.toml` | anything that only wants a base16 palette |
| `ghostty.conf` | Ghostty, which reloads on request |
| `sketchybar.sh` | the omacosy bar's palette |
| `borders.sh` | the ring's palette, and OmniWM-style consumers that expect it |

In the state directory (`~/.config/macthemer/`):

| Path | What it is |
|---|---|
| `current` | symlink to the active pack |
| `current.json` | the resolved palette: palette, tokens, border, bar, alpha |
| `borders.conf` | ring geometry (width, gap, radius, per-app radius) |
| `disabled-agents` | what `install.sh` took over, so `uninstall.sh` can return it |

And at `~/.config/omarchy/current/`: the same theme symlink and `ghostty.conf`
the omarchy convention already expects, so a bar, helper or script on this
machine keeps resolving its files while the desktop migrates. Nothing is asked
to change. `MACTHEMER_COMPAT` moves or, once nothing reads it, drops it.

`current.json` is the seam for everything that is not wired yet. It is written
atomically and carries the palette, the semantic roles and the named border and
bar colours, so an app needs no theme logic of its own and no shell parsing:

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

## The border ring

`borders/borders.swift` draws a ring around the focused window. It is a port of
omacosy's daemon and keeps that revision's behaviour, including the parts that
exist only because of something the window server actually does: SkyLight
notifications instead of polling, the frontmost-pid lookup that skips AppKit's
~1s focus lag, per-window move/resize subscriptions, and wall-clock deferral
gates so a transient miss does not blink the ring. It needs no permissions.

Two things differ from the ported revision:

- geometry comes from `~/.config/macthemer/borders.conf` and the ring colour
  from `current.json`, both watched with kqueue and re-read in place;
- **it covers AeroSpace only.** Under OmniWM the ring parks itself and OmniWM
  draws its own border. mac-themer does not write into OmniWM's settings.

Both workspace-switch sentinel names (`/tmp/macthemer-ws-switch` and
`/tmp/omacosy-ws-switch`) are watched, so the AeroSpace config does not have to
care which project wrote its chord.

`width`, `gap` and `radius` are a concentric set: the ring radius is the
window's corner radius plus `gap` plus half `width`. Change `gap` and move the
radii with it, or the ring fights the window's own corners. The conf file
documents the measured radii for the apps that were measured.

## Tests

```sh
./tests/run.sh                        # unit, golden, CLI sandbox
MACTHEMER_TEST_BUILD=1 ./tests/run.sh # also compile borders.swift
./tests/update-goldens.sh             # rewrite goldens after a renderer change
```

The suite never touches the real desktop: the CLI tests copy the checkout,
point every `MACTHEMER_*` path at a temporary tree and set `MACTHEMER_DRY_RUN=1`,
so applying a theme moves a symlink in `/tmp` instead of taking over the
tester's wallpaper, Ghostty window and Korren config.

The important tests are the pins in `tests/test_render.py`: the bar and border
palettes for all four packs, read off the machine before the move. A change to
the derivation that would restyle a bar fails there rather than being noticed
weeks later.

## Not in this slice

- The Qt pill and `maccer` are not wired to `current.json` yet. The launcher's
  `crates/launcher-ui/src/theme.rs` is still hardcoded greyscale and the pill's
  `Theme.qml` is still its own washi palette; both are meant to read the
  resolved palette and keep their own identity as a named pack.
- OmniWM's border colour is OmniWM's business here. If that changes, it becomes
  another renderer, not more logic in the CLI.
- Wallpaper-to-palette generation is not implemented. The pill carries a
  `Dyn`/matugen path that could feed it back in as a generated pack.

Upstream attribution for the ported code and the redistributed packs is in
[NOTICE.md](NOTICE.md).

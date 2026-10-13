# Third-party notices

mac-themer is MIT (see `LICENSE`). Two pieces of it did not start here.

## omacosy — focused-window border daemon

`borders/borders.swift` is a port of `helper/borders.swift` from
[omacosy](https://github.com/paulsp94/omacosy), MIT, Copyright (c) 2026 Paul
Spende. The port is behaviour-preserving on purpose: the SkyLight event set,
the frontmost-pid lookup that skips AppKit's ~1s focus lag, the subscription
set, the deferred re-check gates and the shroud geometry are all the result of
debugging a real window server, and rewriting them for the sake of a fresh
file would have thrown that away.

Changed from the ported revision:

- styling is read from `~/.config/macthemer/borders.conf` and the ring colour
  from `~/.config/macthemer/current.json`, instead of the omarchy convention;
- OmniWM's own border is left to OmniWM, so the daemon parks the ring there
  rather than claiming it;
- both workspace-switch sentinel names are watched, so the daemon does not
  care which config wrote the chord that touches it.

Everything else is as upstream. Bug reports about ring behaviour should be
reproduced against the upstream revision before being blamed on the port.

## omacosy — theme packs

The four packs in `themes/` (catppuccin, gruvbox, osaka-jade, tokyo-night)
carry the palettes omacosy shipped, redistributed here under the same MIT
licence. Upstream in turn credits their authors: Catppuccin, Gruvbox, Osaka
Jade and Tokyo Night are separate projects with their own licences, and the
background photographs in each pack's `backgrounds/` directory are third-party
images redistributed for personal desktop use.

The `sketchybar.sh` and `borders.sh` palettes were hand-tuned upstream. They
are not copied here — they are reproduced by `lib/macthemer/`, and
`tests/test_render.py` pins the generated values so a change to the derivation
cannot silently restyle a bar.

## omacosy — theme driver behaviour

`bin/mac-themer`'s fan-out (Korren's built-in theme names, the single-image
wallpaper fallback through `osascript` with the path passed as an argument
rather than spliced into script text, and the note that macOS 14+ intermittently
breaks System Events wallpaper scripting) follows the behaviour of omacosy's
`bin/theme-set` and `bin/theme-bg-next`, same licence and author.

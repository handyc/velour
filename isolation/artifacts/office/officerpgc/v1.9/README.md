# officerpg v1.9 — half-block hex world

Resolution-bump fork: ports officemandel's ▀ U+2580 rendering trick
(foreground = upper-half pixel, background = lower-half pixel, one
char-cell carries two stacked colour pixels) into officerpg.

## Why

In v1.8 each hex tile occupied 8 chars wide × 3 chars tall (24
char-cells per tile) and the viewport was a fixed 8×8 = 64 tiles.
Half-block rendering halves the vertical char budget for the same
pixel count, so the per-tile footprint shrinks to 4 chars wide × 2
chars tall (8 char-cells, 1/3 of v1.8) while still showing 4×4 = 16
distinct colour pixels per tile.  Net effect on the same terminal:

| terminal      | v1.8 visible tiles | v1.9 visible tiles | ratio |
| ------------- | ------------------ | ------------------ | ----- |
| 80 × 24       | 64                 | 19 × 11 = 209      |  3.3× |
| 120 × 36      | 64                 | 29 × 17 = 493      |  7.7× |
| 160 × 48      | 64                 | 39 × 23 = 897      | 14×   |

The world map is 128×128 hex tiles (16,384 total).  Even the smallest
terminal viewport now sees ~1.3% of the world at a glance vs v1.8's
~0.4%.

## Build

```
cc -DTINY -std=c99 -Os -Wall \
   -fno-builtin -ffreestanding -nostdlib -nostartfiles -static \
   -Wl,--gc-sections -s -o officerpg officerpg.c
```

GCC 12+ on x86-64 Linux.  Produces a stripped 13 KB static ELF.

## Run

```
./officerpg
```

| key            | action                                    |
| -------------- | ----------------------------------------- |
| `a` `d`        | west / east                               |
| `w` `e`        | north-west / north-east                   |
| `z` `x`        | south-west / south-east                   |
| arrows         | cardinal-only fallback (↑=`w`, ↓=`x`)     |
| `r`            | recentre on (0, 0)                        |
| `q` `ESC` `^C` | quit                                      |

## Design notes

- Terrain is stateless: tile colour at `(wx, wy)` is a pure hash of
  the world coords, blending a low-frequency (`>>3`) cluster signal
  with a per-cell (`>>1`) edge-noise signal so biomes form patches
  with ragged boundaries.  No globals to seed; the world is the same
  every run.
- Sub-pixel texture: each of the 16 colour pixels inside a tile is
  picked between `biome.base` and `biome.accent` by a per-(x,y,px,py)
  hash with a threshold `biome.sprinkle`, so each tile reads as a
  small textured patch rather than a flat fill.
- Hex offset: pointy-top, offset-r.  Odd visible rows shift +2 chars
  (half of CELL_CHARS_W = 4) so the lattice has the right 60° look.
- Player overlay: yellow (226) head pixel + magenta (201) body pixel
  at the viewport centre, deliberately outside any biome's RGB
  family so the player always reads.
- Frame discipline: DEC sync-output (`?2026h/l`) wraps each draw so
  partial frames don't tear during a redraw.  SGR state is tracked
  across a row — we only re-emit `\x1b[38;5;Nm` / `\x1b[48;5;Nm`
  when the foreground or background colour actually changes.
- Window resize: every keypress re-probes `TIOCGWINSZ` so the
  viewport adapts without restarting.

## Not yet in v1.9

The v1.8 systems (NPCs, animals, items, inventory, mood-music,
genome workshop, image+mandel presets, save bundles) are absent
from this fork — v1.9 is a focused demonstration of the half-block
rendering technique and the resulting tile-density increase.  Port
those systems back in v2.0+ once the new render path proves out.

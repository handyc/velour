# officerpg v1.3 — ANSI-C terminal hex-CA RPG

Single-file native port of the JS `officerpghires` browser game.
Static, stripped, no libc, no dynamic allocation, ~46 KB ELF.

## Build

```
cc -DTINY -std=c99 -Os -Wall -Wextra \
   -fno-stack-protector -fno-asynchronous-unwind-tables \
   -fno-unwind-tables -fno-builtin -ffreestanding \
   -ffunction-sections -fdata-sections \
   -nostdlib -nostartfiles -static \
   -Wl,--gc-sections -Wl,--build-id=none \
   -Wl,-z,noseparate-code -Wl,-z,common-page-size=512 -s \
   -o officerpg officerpg.c
```

GCC 12+ on x86-64 Linux. The pre-built binary in this directory was
produced with these exact flags.

## Run

```
./officerpg              # interactive rpg, blocking input
./officerpg saver        # unattended journey-mode screensaver
./officerpg workshop     # interactive 16384-rule genome editor
./officerpg test [opts]  # deterministic walk + state report
./officerpg --help       # full key reference
./officerpg --version
```

`saver` is the safe long-running mode — it walks itself via the
journey planner and respawns on death (HP=0). `test` is the
non-interactive harness; see `--help` for flags.

## Interactive keys

```
wadezx        offset-r hex move (a=W, d=E, w=NW, e=NE, z=SW, x=SE)
i             inventory
m             cast zap
l             toggle live animation
k             open speed-settings panel
0-3           bend terrain (cost MP)
4-7           recolour palette (cost MP)
S             save world bundle (officerpg-state.bin)
L             load world bundle
E             ANSI screenshot (officerpg-shot.ans)
b             pc-speaker chime / BEL fallback
h             toggle animal action halos
u  U          per-cell rule pool: toggle / reseed from mother
M             mood-modulated pc-speaker music (HP ratio picks scale)
G             toggle L-system GA — sprite library drifts over time
q  ESC        quit
```

## WSL note

`b` (pc-speaker) detects WSL via `/proc/sys/kernel/osrelease` and
falls back to terminal BEL. Earlier forks called `KIOCSOUND` on
`/dev/tty1` unconditionally, which wedges the LXSS console driver
hard enough to require a Windows reboot. The runtime detection in
`rpg_is_wsl()` shipped in v0.3 and is the load-bearing piece — do
not remove it.

## Tests

```
./officerpg test --no-io                                     # 30-step baseline
./officerpg test --no-io --per-cell-rules                    # exercise rule pool
./officerpg test --no-io --per-cell-rules --ga-rounds 200    # exercise pool GA
./officerpg test --no-io --steps 100 --seed 42               # longer + custom seed
```

Each prints one line: `test ok · steps=N · pos=X,Y · pool=Y/N ·
per-cell=Y/N · ga=R`. Exit 0 on success.

## Feature parity

This port hits feature parity with `officerpghires` ev67 within
the portable subset. The 16 JS-only features are inherently
non-terminal: 4 Web Audio, 6 sub-cell pixel rendering, 4 browser
modal UIs, and 2 conceptual mismatches (`lite-terminal` is
circular here; `lsystem-genome`'s evolving library is hardcoded in
the C build). See `velour:bidir/management/commands/seed_bidir.py`
for the authoritative table.

## Version history

- v0.1 — baseline ANSI-C port (37,680 B)
- v0.2 — autoplay-stuck, hex-meta-cascade, shot-bundle, pc-speaker
- v0.3 — WSL guard for KIOCSOUND (P0 fix; v0.2 wedged a session)
- v0.4 — death-respawn for unattended journey mode
- v0.5 — per-cell rule pool (`u`)
- v0.6 — pool GA tournament-2 every 60 frames
- v1.0 — feature-parity milestone, extended test harness
- v1.1 — `music-mood` (ev42) on pc-speaker: monophonic A-pentatonic
  modulated by HP ratio (major/minor) and tempo (6 vs 12 frames).
  WSL silently no-ops; non-WSL terminals need privileged access
  to /dev/tty1 (root or `tty` group). Reclassifies one of the
  audio features from N/A to done; stereo/waltz/smooth stay N/A
  on pc-speaker since it's monophonic.
- v1.2 — `lsystem-genome` (ev15): mutable parallel rule buffer
  overrides the const archetypes when the GA touches a slot.
  Tournament-2 every 120 frames within each entity category;
  fitness = expanded F-step count + bbox area; sprite cache
  invalidation per (cat, arch) on slot replacement.  Toggle `G`.
- v1.3 — `genome-workshop` (ev1): new `workshop` subcommand,
  interactive editor for the 16384-rule hex CA.  Navigates by
  situation index 0..16383 (4^7 = self colour + 6 neighbours);
  shows a 7-swatch row of the current situation and a 16×16
  live preview stepped 2 ticks under the active genome from a
  fixed seed.  Edits trigger immediate re-render.  Keys: hl ±1,
  jk ±16, HL ±256, JK ±4096, g/G first/last, 0-3 set, r random,
  x clear, W save (writes hxhnt.seed), q/ESC quit.  Bidir matrix
  now 19 done / 13 na for ANSI-C.

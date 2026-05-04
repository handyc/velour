# wnnr — a tiny Win95-style window in your terminal

Lean and mean. Single .c file, libc + POSIX termios + ANSI 256-colour
escapes, no curses, no SLURM, no third-party libraries. Compiles
clean with `-std=c99 -Wall -Wextra -Wpedantic`.

```
                ┌─────────────────────────────────────────┐
                │ wnnr - window                  _ [] X   │  ← royal-blue title
                ├─────────────────────────────────────────┤
                │ File  Edit  View  Help                  │  ← grey menu bar
                ├─────────────────────────────────────────┤
                │  Position: (35,  6)                     │
                │  Mon May  5 02:13:42 2026               │
                │  Moves: 7                               │
                │                                         │
                │  arrow keys move | r recolour | s save  │
                └─────────────────────────────────────────┘
```

The classic Win95 grey (`#c0c0c0` ≈ ANSI 256 colour 7) for the
window background, royal blue (colour 21) for the title bar, white
top/left bevel + dark-grey bottom/right shadow to fake the 3D look.

## Controls

| key | action |
|---|---|
| ← ↑ ↓ → | drag the window around the desktop |
| `r` | re-roll the title-bar colour (still Win95-y; pick from a small set of bright shades) |
| `s` | save window position + title colour to `./savepoint`, then exit |
| `q` | quit |

On launch, if `./savepoint` exists, the window restores to that
position. The clock auto-refreshes every 5 s.

## Build

```sh
make
```

Or directly:

```sh
cc -std=c99 -O2 -Wall -Wextra -o wnnr wnnr.c
```

## Run

```sh
./wnnr
```

The window centres itself on the terminal automatically — no
arguments. Resize-aware via `TIOCGWINSZ`; falls back to 80×24 if
the ioctl fails.

## What's gone vs. the bash original

- No SLURM (`k`/`l` keys removed).
- No multi-duck mode — one window only.
- No tput dependency. Pure ANSI escapes.

What's left is the spirit of the toy: a single coloured box you
can shove around the screen, with a date readout, save/quit keys,
and a colour re-roll for fun.

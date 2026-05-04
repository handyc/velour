# wnnr — terminal duck toy in C

Faithful translation of [`advanced/wnnr`](https://github.com/handyc/ALICEworkshop/blob/main/advanced/wnnr)
from the ALICE workshop. The original is a small bash script; this
is a single-file C program (libc + POSIX termios + ANSI escapes,
no curses) that does the same thing.

## What it does

- Spawns N coloured "ducks" (text boxes) at random positions on the
  terminal. N defaults to 1..5 random; pass an integer to fix it
  (`./wnnr 8`).
- Each duck shows its `x y` coordinates with its assigned background
  colour, and the current `date` 3 lines below.
- Arrow keys move duck 0 around the screen.
- `r` randomises the foreground + background colours.
- `s` saves the state (positions + colours) to `./savepoint` and exits.
- `q` quits.
- `k` and `l` shell out — by default to `squeue -u $USER` and
  `squeue` (the ALICE workshop's HPC monitor commands). Override
  via `WNNR_K` and `WNNR_L` environment variables to make them run
  whatever you like.

The screen idles for 60 s waiting for a key before redrawing.

## Build

```sh
make
```

Or directly:

```sh
cc -std=c99 -O2 -Wall -Wextra -o wnnr wnnr.c
```

No external libraries — just libc, POSIX termios, and ANSI escape
sequences. Should compile on any recent Linux/macOS/BSD without
fuss.

## Use

```sh
./wnnr            # 1..5 random ducks
./wnnr 8          # exactly 8 ducks
WNNR_K='qstat'   ./wnnr 4   # k key runs PBS qstat instead of squeue
WNNR_L='top -bn1' ./wnnr 4   # l key snapshots top
```

## Differences from the bash original

- **Cursor hidden** while running (`ESC[?25l`/`ESC[?25h`); restored
  on exit including signal-driven exit (Ctrl+C).
- **No `quack1`/`quack2`** with hard-coded SLURM partition colour
  schemes. The `k`/`l` keys still shell out, but to a default
  `squeue` invocation that any cluster user can run, and you can
  point them at any command via env.
- **Save format** is a single line of space-separated ints — same
  semantics as the bash version's `echo "${myX[@]}" "${myY[@]}"
  "${r[@]}" > savepoint`, just emitted by `fprintf`.
- **Drain timeout** for ESC sequences is 200 µs (vs. bash's
  0.0001 s = 100 µs). The longer drain reliably catches arrow keys
  on slow terminals (SSH from outside the data centre).
- **Bounds clamping** on duck 0 movement: x ∈ [0, 78], y ∈ [0, 30].
  The bash version had no clamp — you could send your duck off
  screen.

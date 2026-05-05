# office — eight apps in 12.8 KB

A Win95-style office suite in a single statically-linked Linux x86_64
ELF. No libc, no curses, no third-party libraries — just the same
raw-syscall framework as `wnnr`, scaled up.

```
$ make
office: 9408 bytes
$ ./office
```

The shell launches; type a command, hit Enter:

| command | what it does |
|---|---|
| `notepad <file>` | full edit: arrows move cursor, type to insert, bksp to delete, ^S save, ^Q quit |
| `word <file>` | same edit model as notepad, with word-wrap |
| `mail` | compose To / Subject / Body, ^S writes `outbox.txt` |
| `sheet <csv>` | 8×12 cell grid, arrows navigate, `e` edit, `s` save |
| `paint` | 60×16 ASCII canvas, arrows move, letters paint, `s` writes `canvas.txt` |
| `hex <file>` | 16-bytes-per-line hex+ASCII view of a file |
| `bfc <prog.bf>` | Brainfuck interpreter — runs the program, shows output |
| `exit` | leave the shell |

You can also invoke any subapp directly:

```
$ ./office hex office          # view the binary itself
$ ./office bfc hello.bf
$ ./office sheet data.csv
```

## Why it's small

Same trick as `wnnr`:

- **No libc.** Inline-asm `syscall` wraps `read`/`write`/`open`/`close`/`ioctl`/`exit_group`.
- **`_start` not `main`.** Linker entry skips the whole crt0 + libc init chain.
- **One ELF.** All eight "apps" are functions in one binary; the dispatcher decides by `argv[1]`. Saves seven ELF headers, seven program-header tables, seven copies of every shared helper.
- **Shared draw stack.** Win95 frame, ANSI escape composers, raw-mode termios, key-reading, file load/save are written once and called from every app.
- **One coalesced `write(2)` per frame.** Each app builds its draw into a 16 KB framebuffer in `.bss`, then issues a single syscall to flush.

## Honest scope

- The "compiler" is a Brainfuck interpreter, runs in-process and shows output. A real C compiler is impossible in 16 KB. (Even `xcc700`, my 700-line K&R-subset compiler, is ~50 KB compiled.)
- `mail` writes to `./outbox.txt`. There is no SMTP, no IMAP, no network code.
- `sheet` has no formulas — just a CSV cell grid editor.
- `notepad` and `word` are full editors: cursor positioned at `bcur`, printable chars insert, backspace deletes, enter inserts newline, auto-scroll keeps cursor in view. ^S saves, ^Q quits. The terminal cursor is shown at the active position so you can see what you're typing.
- `paint` paints whatever character you press at the cursor position. `0`-`7` cycles foreground colour.
- `hex` is read-only (scroll only).

## Build

```sh
make            # 12.8 KB stripped, no libc
cc office.c -o office_libc      # ~18 KB libc build (works too via the
                                # int main() fallback)
```

The Makefile passes `-DTINY` so the source compiles with `_start` as
the entry point. Without `-DTINY` you get an `int main()` that links
libc — useful if you want to compile by hand without the flag wall.

## Sibling forks

`office.c` is the baseline. Two extended versions sit alongside it,
each a self-contained fork rather than a dependency on the previous:

- **`office2.c`** — adds three things the baseline didn't do:
  - `hex` becomes a real editor: nibble cursor, `0-9 a-f` overwrite,
    `i` inserts a 0x00 byte, `x` deletes, `^S` saves.
  - `sheet` cells starting with `=` evaluate as a tiny expression:
    `+ - * /`, parens, cell refs `A1..H12`. Recursion depth-capped.
  - `paint` stores a per-cell foreground colour (`canvas_fg[16][60]`)
    so two characters in different colours can sit on the same row.

- **`office3.c`** — adds five more on top of office2:
  - `sheet` gains `SUM(A1:C3)`, `AVG`, `MIN`, `MAX` ranges that mix
    with arithmetic (`=SUM(A1:A3)*2+1`).
  - `hex` gains an ASCII pane: `tab` toggles between hex and ASCII;
    in ASCII mode, printable keys overwrite the byte at cursor.
  - `paint` saves and reloads with colours preserved (`canvas.txt`
    becomes a `<hex><char>` pair stream — round-trips intact).
  - `word` gets `^J` paragraph reflow: collapses runs of whitespace
    in the current paragraph (bounded by `\n\n`) and re-wraps to fit
    `SCREEN_W - 4`.
  - new `files` app: directory browser using raw `getdents64`. Enter
    opens the selected file in `notepad`; `h` opens it in `hex`.

```
make            # builds all three: office, office2, office3
make office3    # just the latest fork
```

Sizes (after `-Wl,-z,common-page-size=512`, which shaves ~2 KB
without breaking the raw `_start`):

| binary  | bytes |
|---------|-------|
| office  | 10240 |
| office2 | 11776 |
| office3 | 14848 |

`-Wl,-z,max-page-size=512` looks similar but **breaks** the binary at
runtime — don't use it. The dispatcher in office3 accepts argv[0]
basename `office`, `office2`, or `office3` interchangeably, so a
symlink with any of those names dispatches correctly.

# office — twelve apps in a single ELF

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
| `find` | grep substring across files in cwd, Enter opens hit in notepad (office4) |
| `calc` | single-line expression evaluator, reuses sheet's formula engine (office4) |
| `mines` | 16×16 Minesweeper, 40 mines, first-click safe (office4) |
| `exit` | leave the shell |

In office4+ the top menu bar is **real**: press **Alt+F / Alt+E / Alt+V / Alt+H**
(DOS mnemonic) or **F10** (Unix-curses convention) to open it. Arrows
navigate, Enter selects, Esc cancels. Underlined letters in the bar
mark the mnemonic, just like Borland and Win95 did. office5 fixed
the column alignment, dimmed unavailable menus, and added a Win95
drop shadow.

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

`office.c` is the baseline. Three extended versions sit alongside it,
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

- **`office4.c`** — adds the suite-feel polish on top of office3:
  - the top menu bar (`File Edit View Help`) is now **real**.
    Activated by **Alt+F/E/V/H** (DOS mnemonics) or **F10** (curses
    convention). Arrow keys navigate; Enter selects; Esc cancels.
    Underlined letters mark the mnemonic.
  - **cross-app clipboard**: `^X` cut, `^C` copy, `^V` paste. Works
    across notepad, word, sheet (cell), hex (16-byte row), and the
    Body field of mail / the input field of calc.
  - new **`find`** app — grep across files in cwd. Enter on a hit
    opens the file in notepad with the cursor on that line.
  - new **`calc`** app — single-line expression input that reuses
    the sheet's `+ - * /`, parens, and SUM/MIN/MAX/AVG evaluator.
  - new **`mines`** app — 16×16 Minesweeper, 40 mines. Arrows move,
    space reveals (first reveal is always safe), `f` toggles a flag,
    `r` resets, `q` exits.

- **`office6.c`** — same apps + fixes as office5; one further fix:
  arrowing left/right between menus now erases the previous pulldown
  before drawing the new one. office5 left the old pulldown on screen
  during navigation, so the user could see two menus active at once
  (e.g. File's "Save" and Edit's "Cut" overlapping). The fix is a
  single body-area teal-fill at the top of each `menu_run` iteration.

- **`office7.c`** — adds two new apps on top of office6 (one per commit):
  - new **`ask`** app — dual-pane LLM chat. History above (you>/ai>
    alternating, hard-wrapped, scroll-pinned to bottom), single-line
    input below. ENTER sends; ^N clears the chat; ^E (or File →
    Settings) opens an inline editor for `api_key` / `endpoint` /
    `model`, persisted to `./office7.conf` (mode 0600). HTTPS is
    handled by `fork()` + `execve("curl", ...)` — no in-process TLS,
    just `curl -sS -X POST -H Authorization: Bearer $K -d @req.json`
    against an OpenAI-compatible Chat Completions endpoint
    (`https://api.openai.com/v1/chat/completions` by default; works
    with any provider that speaks the same wire format). The reply
    is parsed by greping for the first `"content":"…"` in the JSON.
    Suite clipboard `^V` pastes into the input field. The conf file
    is gitignored.
  - new **`garden`** app — interactive-evolution colour/layout
    breeder (Karl-Sims / Dawkins biomorph style). 64 `Genome`
    instances (16 bytes each, 1 KB total) shown as an 8×8 grid of
    thumbnails. Each genome controls the suite's title bar, menu
    bar, desktop, selected-item, drop-shadow, and accent colours,
    plus a clock-corner pip, border style, and mnemonic-underline
    flag. The previously-hardcoded `COL_*` macros now redirect to
    the global `g_genome`, so all twelve other apps automatically
    repaint with whichever genome is active. SPACE marks a thumb
    as a parent; ENTER advances the generation (uniform crossover
    of two random marked parents per unmarked slot, then per-byte
    mutation at ~9% rate); P previews the cursor's genome by
    painting the suite chrome with those colours and a fake
    selected menu title; R re-randomises the population; S writes
    `./garden.bin` (1040 B); the file is auto-loaded on next
    launch. MVP is 80×24 with 10×3 thumbs filling the screen;
    on terminals reporting larger size via TIOCGWINSZ the thumbs
    grow and the spare rows show a top status (`gen N · M marked`)
    and a bottom keybind hint.

- **`office5.c`** — same apps as office4, but fixes the menu display
  bugs that surfaced once office4 hit a real terminal:
  - Pulldown columns now line up with the title letter. office4 had
    the per-title step at `slen+3` instead of `slen+2`, so each
    successive menu's pulldown drifted right (Edit was 1 col off,
    View 2, Help 3).
  - The menu bar now blanks all 80 columns. office4 left the rightmost
    4 cells in the teal desktop background.
  - `Alt+letter` on a menu the current app doesn't have is now a
    no-op. office4 silently auto-advanced to the next non-empty
    menu (so `Alt+V` on notepad opened Help). Arrow ←/→ navigation
    inside an open menu still skips empty menus.
  - Titles for menus the current app doesn't have are dimmed (gray
    foreground), so a glance at the bar shows you Edit isn't
    available in `paint`.
  - The status line at the bottom changes to
    `ESC cancel | ARROWS navigate | ENTER select` while a menu is
    open, replacing whatever the app set.
  - Pulldowns now drop a 1-cell dark shadow on the right and bottom,
    matching Win95's chrome.

```
make            # builds all seven
make office7    # just the latest fork
```

Sizes (after `-Wl,-z,common-page-size=512`, which shaves ~2 KB
without breaking the raw `_start`):

| binary  | bytes | cap   |
|---------|-------|-------|
| office  | 10240 | 16 KB |
| office2 | 11776 | 16 KB |
| office3 | 14848 | 16 KB |
| office4 | 25160 | 32 KB |
| office5 | 25160 | 32 KB |
| office6 | 25160 | 32 KB |
| office7 | 37800 | 64 KB |

The 16 KB cap held through office3. office4 adds three full new
apps plus a menu engine, clipboard infrastructure, and per-app
About bodies — about 7 KB of extra code, so the cap moved up to
32 KB. office5 is byte-for-byte the same size as office4 because
the menu fixes are pure logic adjustments (the +3 → +2 step, the
no-auto-advance check, the dim-empty-titles branch, the drop
shadow, the menu-mode status string) net out roughly even with
the small simplifications they replace.

`-Wl,-z,max-page-size=512` looks similar but **breaks** the binary at
runtime — don't use it. The dispatcher in office7 accepts argv[0]
basename `office`, `office2`, `office3`, `office4`, `office5`,
`office6`, or `office7` interchangeably, so a symlink with any of
those names dispatches correctly.

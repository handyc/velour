# office — eight apps in 9408 bytes

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
| `notepad <file>` | line-scrolling text viewer (arrows scroll, `s` save, `q` back) |
| `word <file>` | same as notepad, with word-wrap |
| `mail` | compose To / Subject / Body, ctrl-S writes `outbox.txt` |
| `sheet <csv>` | 8×12 cell grid, arrows to navigate, `e` edit, `s` save |
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
- `notepad` and `word` scroll but don't insert/delete characters yet (binary size is the constraint; an in-place edit buffer + cursor adds ~1 KB).
- `paint` paints whatever character you press at the cursor position. `0`-`7` cycles foreground colour.
- `hex` is read-only (scroll only).

## Build

```sh
make            # 9.4 KB stripped, no libc
cc office.c -o office_libc      # ~17 KB libc build (works too via the
                                # int main() fallback)
```

The Makefile passes `-DTINY` so the source compiles with `_start` as
the entry point. Without `-DTINY` you get an `int main()` that links
libc — useful if you want to compile by hand without the flag wall.

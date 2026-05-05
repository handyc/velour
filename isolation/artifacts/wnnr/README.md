# wnnr

A Win95-style window in your terminal. **1532-byte stripped binary**
on Linux x86_64 — smaller than the 2 KB bash original.

```
   wnnr - window         _ [] X       ← royal blue title bar
   File  Edit  View  Help             ← grey menu bar
                                      ← grey content
                                          (8 rows of empty space)
```

## How it gets so small

- **No libc.** Raw `syscall` instruction via inline asm for `read`,
  `write`, `ioctl`, `exit_group`. No glibc dynamic linker, no startup
  code, no eh_frame, no relocation tables.
- **`_start` instead of `main`.** Skips libc's `__libc_start_main`
  and the whole crt0 chain.
- **Hand-rolled itoa + write coalescing.** One frame goes out as a
  single `write(2)` syscall, no `printf`.
- **Section-stripped ELF.** `strip --strip-section-headers` removes
  the section table; the loader doesn't need it. Compiler flags
  also drop `.note.gnu.property`, `.comment`, `.eh_frame`,
  unused functions, and async unwind tables.

## Build & run

```sh
make
./wnnr
```

Arrow keys move the window. `q` quits. That's it.

## Source

```sh
$ wc -c wnnr.c
~2.4 KB    # source is a bit longer than the libc version
$ ls -l wnnr
1532       # but the binary is half the size
```

## Notes

- **Linux x86_64 only.** Syscall numbers and termios layout are
  baked in. Porting to ARM64 = swap the syscall numbers + maybe
  the inline asm. Porting to BSD/macOS = bigger refactor; their
  termios uses different ioctl numbers.
- **No fallback if section-header strip fails.** Old binutils
  (< 2.40) don't have `--strip-section-headers`; the Makefile
  swallows the error and you'll get a ~1880-byte binary instead.
  Still small.

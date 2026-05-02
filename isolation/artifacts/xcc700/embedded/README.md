# xcc700 — embedded port

Lets the 700-line xcc700 mini-C compiler run **inside** an ESP32-S3
SuperMini program (or any other process) so callers can compile C
source to Xtensa-LX7 ELF without touching the filesystem or spawning
a subprocess. The original CLI behaviour is unchanged — this is a
sibling layer that wraps the verbatim vendor source.

## Files

```
embedded/
  xcc_embedded.h     # public API: xcc_compile() + xcc_result_t
  xcc_shim.c         # stdio/syscall replacements + xcc_compile() impl
  xcc_vendor_wrap.c  # #define-substitutes libc, then #includes vendor
  test_host.c        # smoke + diff-vs-CLI test (host build)
  build_test.sh      # builds + runs test_host on host gcc
  README.md          # this file
```

The vendor source under `../vendor/xcc700.c` is **never modified** —
we wrap it via macro substitution. To update upstream, follow the
recipe in the parent `../README.md`.

## Public API

```c
#include "xcc_embedded.h"

xcc_result_t r = xcc_compile(c_src, c_src_len);
if (r.exit_code == 0) {
    // r.elf       — uint8_t* into an internal heap buffer
    // r.elf_size  — bytes, ~480-2000 typical for slot-sized programs
    use_elf(r.elf, r.elf_size);
} else {
    // r.err       — null-terminated, captured xcc700 stderr
    log_error(r.err);
}
```

The result's `elf` pointer aliases an internal buffer that's freed
on the next call. Copy it out if you need it longer.

**NOT thread-safe** — xcc700 keeps state in file-scope globals. Wrap
in a mutex if compiling from multiple FreeRTOS tasks.

## How the rewire works

`xcc_vendor_wrap.c` `#define`s every libc symbol the vendor uses
(`open`, `close`, `read`, `write`, `lseek`, `printf`, `exit`, `clock`,
plus `main` → `xcc_main_real`) before `#include`-ing
`../vendor/xcc700.c`. The `enum { O_RDONLY=0, O_WRONLY=1, ... }` the
vendor declares stays untouched — the shim's `xcc_open` ignores the
flags anyway since I/O is in-memory.

`xcc_shim.c` lives in a separate translation unit so it can include
real `<stdio.h>` / `<stdlib.h>` / `<string.h>` without the system
prototypes fighting the relaxed ones the vendor declares (e.g. real
`strtol` returns `long` but the vendor declares it `int`-returning;
on a 32-bit target this is fine, but the headers can't see both).

## Verified

- Host build (`./build_test.sh`):
  - Embedded `xcc_compile()` produces a valid Xtensa ELF in-process.
  - **Byte-for-byte equal** to the vendor CLI's output for the same
    source. Repeat-call works (state reset is correct). Negative
    inputs return failure with captured stderr.
- ESP32-S3 SuperMini build pulls both shim + wrap TUs via
  `build_src_filter` in
  `isolation/artifacts/hex_ca_class4/esp32_s3_xcc/platformio.ini`.

## Memory budget

- Compiler code: ~30 KB Flash on Xtensa.
- Compiler peak RAM: input source buffer + a 32 KB code buffer + a
  2 KB rodata buffer + a 4 KB name buffer + a few small fixed tables.
  Order **50–60 KB** for typical slot-sized programs.
- Output ELF stays in heap until the next call or `xcc_free_output()`.

## xcc700 grammar quirks

(For callers writing C that will hit this compiler.)

- Only `//` comments. No `/* */`.
- Declarations MUST initialise: `int x = 42;` not `int x; x = 42;`.
- No `for` / `do` / `switch` / `struct` / `union` / `typedef` /
  `float` / `double` / preprocessor.
- `while`, `if`/`else`, `int`/`char`/`void`, pointers, arrays,
  function definitions are supported.

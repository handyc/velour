# xcc700 — vendored mini-C compiler for Xtensa

Vendored copy of [valdanylchuk/xcc700](https://github.com/valdanylchuk/xcc700)
(MIT-licensed, ~700 lines, single C file). Targets Xtensa LX7 — the
ESP32-S3 SuperMini's CPU — and emits a relocatable ELF that the
ESP-IDF `elf_loader` component can load + link at runtime.

## Why we vendor it

Velour wants on-device + on-host compilation of small C functions so
we can:

1. **Phase 1 (current).** Compile arbitrary C source from the Velour UI
   into Xtensa ELF as a download — proves xcc700 works in our pipeline
   and surfaces its C-subset rough edges before we commit to anything
   firmware-side.
2. **Phase 2 (planned).** Stand up a sister PlatformIO project where
   the ESP32-S3 exposes `POST /load-elf` over WiFi, runs ESP-IDF
   `elf_loader` on the uploaded blob, and calls `void run(void)` from
   it. Browser → server → device → execute.
3. **Phase 3 (planned).** Refactor the existing hex-CA firmware so
   its hot loop goes through a fixed function-pointer table (stable
   indices for `step`, `score`, `gpio_drive`, `mutate`, …). An
   uploaded ELF can then atomically swap one entry. Watchdog-revert
   on crash. This is what makes "evolved code patches" possible.

## What xcc700 supports

A deliberately small C subset:

- `if/else`, `while`, function defs + calls
- `int`, `char`, pointers, arrays
- Basic arithmetic + bitwise ops
- Single .c file in, single REL ELF out

What it **doesn't** support:

- `for` / `do` / `switch`
- `struct` / `union` / `typedef`
- `float` / `double` / `long`
- `#include` / `#define` (no preprocessor)
- Multi-line comments
- Global initialisers (.bss only, no .data)
- Real type checking, error reporting, optimisation

The constraints are a feature, not a bug — small grammar = small
mutation space, which matters when the next phase is "evolve C source
that mutates the engine itself."

## Build

```
./build.sh       # outputs ./xcc700 (host x86-64 binary)
```

## Use it directly

```
./xcc700 my_source.c -o my_source.elf
file my_source.elf
# → ELF 32-bit LSB relocatable, Tensilica Xtensa
```

## Use it through Velour (Phase 1, in progress)

`POST /s3lab/compile/` will accept C source from a textarea and return
the resulting Xtensa ELF as a download. See `s3lab/views.py` once it
lands.

## License

MIT (upstream). See `vendor/LICENSE`.

## Updating the vendor copy

Single source file; just re-fetch when upstream releases:

```
curl -sL https://raw.githubusercontent.com/valdanylchuk/xcc700/main/xcc700.c \
     -o vendor/xcc700.c
curl -sL https://raw.githubusercontent.com/valdanylchuk/xcc700/main/LICENSE \
     -o vendor/LICENSE
./build.sh
```

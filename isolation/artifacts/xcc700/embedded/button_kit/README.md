# xcc_button_kit

Cycle baked-in C snippets via a button press. Each press compiles
the next snippet via the embedded xcc700 and hands the resulting
Xtensa-LX7 ELF to a caller-supplied apply callback that does the
actual hot-load (or whatever the target needs).

Designed for the 5 HTTP-less ESP firmwares — they have
`xcc_compile()` linked in but no network endpoint to drive it. This
kit is the thinnest possible trigger surface.

## Files

```
button_kit/
  xcc_button_kit.h    public API (5 functions)
  xcc_button_kit.cpp  implementation (~80 LOC)
  README.md           this file
```

## Wiring into a target

Add the kit to the target's `platformio.ini` (the embedded compiler
itself was already added during the 2026-05-02 sweep):

```ini
build_flags =
    ...existing...
    -I../../xcc700/embedded/button_kit

build_src_filter =
    +<*>
    +<../../../xcc700/embedded/xcc_shim.c>
    +<../../../xcc700/embedded/xcc_vendor_wrap.c>
    +<../../../xcc700/embedded/button_kit/xcc_button_kit.cpp>
```

In `main.cpp`:

```cpp
#include "xcc_button_kit.h"

// Define your snippet table — these become the "channels" the button
// cycles through. Snippets follow the xcc700 dialect (only //
// comments, declarations must initialise, no for/switch/struct).

static const char SNIPPET_IDENTITY[] =
  "void step(char *genome, char *in, char *out) {\n"
  "  int i = 0;\n"
  "  while (i < 256) { out[i] = in[i]; i = i + 1; }\n"
  "}\n";

static const char SNIPPET_INVERT_K4[] =
  "void step(char *genome, char *in, char *out) {\n"
  "  int i = 0;\n"
  "  while (i < 256) { out[i] = 3 - in[i]; i = i + 1; }\n"
  "}\n";

static const char SNIPPET_XOR_NEIGHBOUR[] =
  "void step(char *genome, char *in, char *out) {\n"
  "  int i = 0;\n"
  "  while (i < 256) {\n"
  "    int n = i + 1;\n"
  "    if (n >= 256) n = 0;\n"
  "    out[i] = in[i] ^ in[n];\n"
  "    i = i + 1;\n"
  "  }\n"
  "}\n";

static const char *const SNIPPETS[] = {
    SNIPPET_IDENTITY,
    SNIPPET_INVERT_K4,
    SNIPPET_XOR_NEIGHBOUR,
};

// Apply callback — this is where you actually use the ELF. Typical
// pattern: load_elf_text into IRAM, cast entry to your slot's
// signature, swap a function pointer the main loop calls. See
// hex_ca_class4/esp32_s3_xcc/main.cpp for the canonical reference.
typedef void (*step_fn_t)(char *, char *, char *);
static step_fn_t live_step = nullptr;
static void apply_step(int idx, const char *src, const uint8_t *elf, int n) {
    // ... load_elf_text(elf, n, ...) into exec memory ...
    // live_step = (step_fn_t)entry;
    Serial.printf("[apply] snippet %d → %d B ELF, would patch step()\n",
                  idx, n);
}

void setup() {
    Serial.begin(115200);
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    xcc_button_register_snippets(SNIPPETS,
        sizeof(SNIPPETS) / sizeof(SNIPPETS[0]));
    xcc_button_set_apply(apply_step);
    // Compile + apply the first snippet so the device boots in a
    // known state (alternative: leave live_step = baked-in default).
    xcc_button_reapply();
}

void loop() {
    // Your debounce — replace with whatever pattern your target
    // already uses. The kit doesn't care.
    static int prev = HIGH;
    int now = digitalRead(BUTTON_PIN);
    if (prev == HIGH && now == LOW) {
        delay(20);                 // crude debounce
        if (digitalRead(BUTTON_PIN) == LOW) {
            xcc_button_advance();  // compile next snippet, fire apply
        }
    }
    prev = now;
    // ...rest of your loop (CA tick, render, etc.)...
}
```

## API

```c
void xcc_button_register_snippets(const char *const *snippets, int n);
void xcc_button_set_apply(xcc_button_apply_t cb);

int  xcc_button_advance(void);   // → next index on success, -1 on fail
int  xcc_button_reapply(void);   // re-compile current (no advance)

int  xcc_button_active(void);    // current index (or -1)
int  xcc_button_total(void);     // n
const char *xcc_button_active_src(void);
```

The apply callback signature:
```c
typedef void (*xcc_button_apply_t)(int idx, const char *src,
                                    const uint8_t *elf, int elf_size);
```

The `elf` pointer aliases an internal buffer owned by xcc_embedded;
copy it out (or finish your hot-load) before the next
`xcc_button_advance()` call.

## What the kit does NOT do

- **Debouncing** — caller's responsibility.
- **GPIO wiring** — caller picks the pin / trigger.
- **Slot management** — apply callback decides what to patch.
- **Persistence** — active-index is RAM only; resets on boot. If you
  want last-used to survive reboot, write `xcc_button_active()` to
  LittleFS in the apply callback and read it back in setup().

## Suggested per-target snippet themes

Each of the 5 HTTP-less targets has a natural slot to swap:

| target | hot-loop slot | snippet idea |
|---|---|---|
| `hex_ca_class4/esp32_s3_full`  | `step(genome, in, out)`     | identity / invert / xor-neighbour / drainsink |
| `hex_ca_class4/esp32_s3_gpio`  | `gpio(grid, levels)`        | mirror / blink / xor-parity / mask-low-4 |
| `hex_ca_class4/esp_st7735s`    | `render(prev, cur, rgb565)` | grayscale / diff-only / single-channel |
| `hexnn_search/esp32_s3`        | `fitness(genome, seed)`     | density / variance / cycle-bonus |
| `oneclick_class4/esp32_s3`     | same as full                | same |

Same snippet table can be reused across compatible targets.

# Hex-CA on-board + xcc700 hot-load — ESP32-S3 SuperMini

Fork of `esp32_s3_full/` that pairs the classic on-device pipeline
(GA hunt → CA run → TFT + GPIO) with **WiFi-driven code hot-load**.
The matching browser end is `/s3lab/compile/` on Velour: write C,
compile to Xtensa LX7 ELF, push to the device.

This is **Phase 2** of the compile-on-device arc. Phase 3 — actually
hot-swapping CA fitness/step/render/GPIO callbacks via a fixed
function-pointer table — comes after the upload + load path is solid.

## What's added vs. esp32_s3_full

| feature             | how                                       |
|---------------------|-------------------------------------------|
| WiFi STA            | reads `/wifi.txt` (line 1 SSID, line 2 password) |
| AP fallback         | `hexca-setup` SSID, password `helloboard`, no creds present |
| mDNS                | `hexca.local` once joined to a network    |
| HTTP server :80     | `WebServer` from arduino-esp32             |
| Status              | `GET /` HTML, `GET /info` JSON             |
| WiFi setup          | `POST /wifi` with `ssid` + `password`     |
| ELF upload          | `POST /load-elf` (raw body), saved to `/loaded.elf` |
| ELF run (stub)      | `POST /run-elf` — parses, prints summary, no execute yet |

## First-time setup

1. Flash: `pio run -t upload`
2. Open `pio device monitor`. Without `/wifi.txt`, the board starts
   AP mode `hexca-setup` (password `helloboard`, IP `192.168.4.1`).
3. From a phone or laptop, join that AP and POST your home creds:
   ```
   curl -X POST http://192.168.4.1/wifi -d 'ssid=YOUR_SSID&password=YOUR_PASS'
   ```
   The board persists them to `/wifi.txt` and reboots into STA mode.
4. After it joins, find it at `http://hexca.local/` (or by IP printed
   to Serial).

## Pushing a compiled ELF

Once on the LAN:

```
# Build via /s3lab/compile/, then save the downloaded a.elf locally.
curl -X POST --data-binary @a.elf http://hexca.local/load-elf
curl -X POST http://hexca.local/run-elf
```

`POST /load-elf` validates ELF magic + `e_machine == 0x5e` (Tensilica
Xtensa) before saving. `POST /run-elf` (Phase 2) parses the saved ELF
and prints the entry point + .text size to Serial. **It does not yet
execute the code** — Phase 3 will, once the function-pointer table
is in place.

## What does NOT change

The CA hunt + run loop is byte-identical to `esp32_s3_full/`. WiFi
runs alongside it; `server.handleClient()` is called once per tick.
If WiFi is unreachable the rest of the firmware runs normally.

## Memory notes

The arduino-esp32 WiFi + WebServer stack adds ~50 KB RAM at runtime.
With the existing 156 KB base from `esp32_s3_full/`, expected peak is
~210 KB / 320 KB DRAM (66%). PSRAM is still untouched. Plenty of
headroom for the elf_loader integration in Phase 2.5.

## Phase 3 — slot table + native ELF loader (SHIPPED)

The hot loop calls every per-tick action through `HotSlots HOT`.
A loaded ELF can replace any one slot:

```
POST /run-elf?slot=step|render|gpio
```

Currently swappable slots and their ABIs (xcc700-compatible C):

```
// step: hex CA tick. genome = 4096 B; in/out = 256 cells each.
void step(char *genome, char *in, char *out);

// render: pure data out. Write desired RGB565 colour per cell into
// rgb565[i*2..i*2+1] (low byte first). 0xFF 0xFF = "skip this cell."
// Firmware blits the buffer; loaded code never calls tft.fillRect.
void render(char *prev, char *cur, char *rgb565);

// gpio: pure data out. Write desired HIGH/LOW per binding into
// levels[i]. Firmware does the digitalWrite; loaded code doesn't
// need any external symbols.
void gpio(char *grid, char *levels);
```

`POST /reset-slots` reverts everything to the baked-in defaults.

**Native ELF loader** (`load_elf_text` in `src/main.cpp`): walks the
ELF section header table, finds `.text`, allocates IRAM via
`heap_caps_malloc(MALLOC_CAP_EXEC | MALLOC_CAP_8BIT)`, copies, calls
`__builtin___clear_cache` for icache invalidation, and casts the
entry pointer to the slot's typedef.

Scope is intentionally narrow: ELF32/Xtensa, single .text section,
no external symbols, no `.data`/`.bss`, no relocations resolved.
Loaded code must be self-contained — pure functions over args + stack
locals + arithmetic. `.text` is capped at 32 KiB.

**End-to-end:** write C in `/s3lab/compile/`, click "Compile + push",
and the new slot kicks in on the next CA tick. No re-flash.

## Phase 3.5+ backlog

- Symbol bridge (let loaded code call `serial_println`, etc. via
  function-pointer table indices — needs xcc700 to grow function-
  pointer call syntax, or a manual indexed-call helper).
- Software watchdog: detect a crashed slot mid-tick and auto-revert
  before the chip TWDT-resets.
- More slots: `fitness` (hunt-time), `mutate`, `palette_invent`.
- Multi-section ELFs once a relocation resolver lands.

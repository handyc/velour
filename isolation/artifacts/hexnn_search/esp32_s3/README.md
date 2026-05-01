# HexNN class-4 hunter — ESP32-S3 SuperMini

Direct port of `../pi4.py` (and of the in-browser bench at
`/hexnn/`). Runs the Hunt + Refine GA on-device, persists the elite
to LittleFS, emits a HexNN-genome-v1 JSON tail on USB CDC.

## Behaviour

On every reset:

1. Mount LittleFS (formats on first boot).
2. Load `/elite.bin` (HXNN magic + 1-byte K + 1-byte n_log2 + N×7 keys
   + N outs). Bootstrap a random genome on first boot and persist as
   `/elite.bin`.
3. Run a Hunt round (broad: half mutated, half random) followed by a
   Refine round (narrow: all mutated from the elite).
4. Re-bin the elite and persist back to `/elite.bin`.
5. Step the live grid every `TICK_MS` ms; print the elite as
   `hexnn-genome-v1` JSON on USB CDC every 10 ticks.

The wire format is byte-identical to the browser export, so an
`/elite.bin` pulled off the device with `mklittlefs` decodes
straight back into `pi4.py --input` — and the JSON the device
prints can be pasted into the `/hexnn/` page's import flow.

## Build & flash

```
pio run -t upload
pio device monitor
```

`monitor_speed` is 115200 but it's USB CDC so the value is cosmetic.

## Memory footprint (default config: K=4, n_log2=11, POP=8)

- Population:     8 × 16,384 = 128 KB (BSS)
- Next-gen swap:  same         128 KB (BSS)
- Elite + scratch: 2 × 16 KB =  32 KB (BSS)
- Bin arena:                    16 KB (BSS)
- Two grid arenas (16×16):     0.5 KB (BSS)
- **Total static RAM:         ~305 KB** (out of 512 KB SRAM)

No PSRAM needed at this configuration. To match the browser default
(`n_log2 = 14`, 16,384 prototypes per genome) you must either drop
`POP_SIZE` to 2, or enable PSRAM.

## Differences from the Pi reference

- No web UI. Pair with a separate sketch (or paste the printed JSON
  into the browser bench) if you want visual rendering.
- PRNG is mulberry32 seeded from `esp_random()` at boot, then runs
  deterministically — the same boot seed reproduces the same hunt.
  The Pi version also uses mulberry32 with a CLI `--seed`, so the
  two engines can be made to agree bit-for-bit by passing the boot
  seed printed on USB CDC into `pi4.py --seed=<value>`.
- Self-replication writes to LittleFS, not to a sibling executable.

## Differences from Condenser

This is the **Isolation** version of the same port.  Condenser also
emits an ESP32-S3 build (see `condenser/distill_hexnn.py` and
http://localhost:7777/condenser/) — that one is a single Arduino
sketch with a Wi-Fi web UI, baked-in Wi-Fi creds, and a server-side
SVG render.  It is generated programmatically from a Python f-string
template every time you click the button.

The Isolation version is a hand-curated PlatformIO project — multi-
file, focused on being checked out and compiled by hand, with a
cataloged platform axis (cli / compact / attiny / ESP / Pi) tracked
in the `Pipeline` model.  It produces no web UI; the device prints
to USB CDC.  Same algorithm, different packaging philosophy.

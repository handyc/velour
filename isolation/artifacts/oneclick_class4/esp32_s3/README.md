# oneclick hex-CA class-4 hunter — ESP32-S3 SuperMini

Direct port of `../hunter.c` (GA mode). Runs the hunt on-device, writes
winners to LittleFS, emits hex on USB CDC.

## Behaviour

On every reset:

1. Mount LittleFS (formats on first boot).
2. Load `/seed.bin` (4104 bytes: `HXC4` magic + 4-byte palette + 4096-byte
   packed genome). Bootstrap random palette + identity genome on first
   boot and persist as `/seed.bin`.
3. Run a 30-agent / 40-generation GA on a 14×14 hex grid.
4. Score top 3 winners across 3 tournament seeds.
5. Save each winner as `/winner_<N>.bin` and print its hex on USB CDC.

The 4104-byte tail format is byte-identical to `../hunter.c`, so
`/winner_<N>.bin` pulled off the device with `mklittlefs` (or any
LittleFS reader) drops straight back in as a Linux engine tail:

```
cat hunter_engine winner_3.bin > my_hunter && chmod +x my_hunter
```

## Build & flash

```
pio run -t upload
pio device monitor
```

`monitor_speed` is 115200 but it's USB CDC so the value is cosmetic.

## Memory footprint

- Population: 30 × 4096 = 120 KB (BSS)
- Palettes:   30 × 4 = 120 B
- Two grid arenas + working buffers: ~10 KB
- Total static RAM: ~135 KB (out of 512 KB SRAM)

No PSRAM needed for this configuration. PSRAM only becomes interesting
if you bump POP past ~75.

## Differences from the Linux hunter

- No display/animate mode. Pair with the ST7735S sketch in
  `../hex_ca_class4/esp_st7735s/` if you want visualisation.
- Self-replication writes to LittleFS, not to a sibling executable.
- PRNG is xorshift32 seeded from `esp_random()` rather than libc `rand()`.
  The grid-seeding LCG is unchanged (Park-Miller) so scoring is bit-for-bit
  reproducible given the same `grid_seed`.

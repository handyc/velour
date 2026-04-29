# Hex-CA on-board full pipeline — ESP32-S3 SuperMini

Single binary that combines all three S3 artifacts:

1. **Hunt** — GA over POP=30 / GENS=40 (same as `oneclick_class4/esp32_s3/`)
2. **Display** — ST7735S 80×160 panel, 14×14 grid at 5 px per cell with
   hex-stagger (same engine as `hex_ca_class4/esp_st7735s/`)
3. **GPIO drive** — cell→pin bindings via `/gpio_map.txt` (same format
   as `hex_ca_class4/esp32_s3_gpio/`)

## Boot sequence

1. Mount LittleFS, init TFT, configure GPIO outputs.
2. **Hunt phase (~10–30 s)** — TFT shows generation counter, best /
   mean fitness, and a colour-coded progress bar that turns
   red → yellow → green as best fitness climbs.
3. Save top winner as `/winner.bin` (4104-byte hunter-tail format,
   compatible with the standalone hunter and actuator sketches).
4. **Run phase (forever)** — TFT renders the live CA at TICK_MS
   cadence (default 300 ms = 3 Hz), GPIO pins are driven from the
   `/gpio_map.txt` bindings, both updated each tick.

Press the board's reset button to run another hunt.

## Pin map

| function       | pins                          |
|----------------|-------------------------------|
| TFT (built in) | SCK 12, MOSI 11, DC 4, CS 5, RST 6, BL 7 |
| GPIO outputs   | per `/gpio_map.txt` (default: 1, 2, 3, 8) |

**Avoid** in `/gpio_map.txt`:

- 4–7, 11–12 (TFT — sketch will warn if you use them)
- 19, 20 (USB D-/D+ — will kill Serial)
- 0 (BOOT)
- 26–32 (octal SPI flash on some variants)
- 33–37 (octal PSRAM on some variants)

Safe defaults on most SuperMini variants: 1, 2, 3, 8, 9, 10, 13, 14, 21.

## `/gpio_map.txt` format

```
cell_x,cell_y,gpio_pin,state_mask
```

`state_mask` is a 4-bit hex value. Bit N set ⇒ pin HIGH when cell
value == N. Examples:

| mask  | meaning                                   |
|-------|-------------------------------------------|
| `0x8` | HIGH only when cell == 3                  |
| `0x7` | LOW only when cell == 3 (others HIGH)     |
| `0xA` | HIGH on states 1 and 3 (alternating)      |
| `0xF` | always HIGH; `0x0` always LOW             |

A default file is written on first boot.

## Compile-time tuning

Edit the `#define`s at the top of `src/main.cpp`:

| macro     | default | meaning                              |
|-----------|---------|--------------------------------------|
| `POP`     | 30      | GA population                        |
| `GENS`    | 40      | GA generations                       |
| `TICK_MS` | 300     | run-phase tick period (ms)           |
| `CELL`    | 5       | TFT cell size in pixels              |

For fast hardware sequencing during the run phase, drop `TICK_MS`
to 50 (20 Hz) or below.

## Memory budget (per build output)

```
RAM:   156 KB / 320 KB DRAM (47.6%)
Flash: 316 KB / 3.3 MB     (9.5%)
```

Peak RAM is during the hunt; ~120 KB is the GA population which sits
unused after the run phase begins. Adding the TFT libraries on top of
the hunter cost ~5 KB RAM. Comfortable margin; no PSRAM needed.

## Build & flash

```
pio run -t upload
pio device monitor
```

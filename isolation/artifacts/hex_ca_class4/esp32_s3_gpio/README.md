# Hex-CA GPIO actuator — ESP32-S3 SuperMini

Runs an evolved hex-CA ruleset in memory and uses configured cells to
drive GPIO output pins. Sibling of `../esp_st7735s/` — same engine,
different output device. Where the TFT sketch displays the CA as
pixels, this sketch turns it into a hardware sequencer.

## Inputs (LittleFS)

- **`/genome.bin`** — 4104-byte tail in the same format the hunter
  emits as `winner_<N>.bin`: `HXC4` magic + 4 palette bytes + 4096-byte
  packed genome. Drop a real winner here for class-4 dynamics. If the
  file is missing or invalid, the sketch falls back to a random genome
  (almost certainly class-1 garbage) and warns on Serial.

- **`/gpio_map.txt`** — one binding per line:

  ```
  cell_x,cell_y,gpio_pin,state_mask
  ```

  `state_mask` is a 4-bit value (`0x0`..`0xF`). Bit N is set ⇒ the pin
  goes **HIGH** when the cell value equals **N**.

  | mask  | meaning                               |
  |-------|---------------------------------------|
  | `0x8` | HIGH only when cell == 3              |
  | `0x7` | LOW only when cell == 3 (others HIGH) |
  | `0xA` | HIGH on states 1 and 3 (alternating)  |
  | `0xF` | always HIGH                           |
  | `0x0` | always LOW                            |

  `#` lines are comments. A default file is written on first boot
  with four pins watching a horizontal strip of cells.

## Compile-time config

Edit the `#define`s at the top of `src/main.cpp`:

| macro          | default | meaning                              |
|----------------|---------|--------------------------------------|
| `GRID_W`       | 14      | grid width                           |
| `GRID_H`       | 14      | grid height                          |
| `TICK_MS`      | 1000    | tick period; 1 Hz default            |
| `MAX_BINDINGS` | 64      | max cell→GPIO bindings parsed        |

For fast hardware sequencing drop `TICK_MS` to 1–10 ms; the engine
itself can sustain ~kHz on the S3.

## Build & flash

```
pio run -t upload
pio device monitor
```

The first boot writes a default `/gpio_map.txt`. To replace `/genome.bin`
without re-flashing the sketch, build a `data/` directory with the file
and use `pio run -t uploadfs`.

## Pin gotchas (ESP32-S3 SuperMini)

- GPIO 19 / 20 are the USB-OTG D-/D+ lines. Driving them will kill
  USB CDC (Serial). The sketch warns if you bind to them.
- GPIO 0 is BOOT — usable as output but goes through a button on most
  SuperMini layouts.
- GPIO 26–32 are reserved for octal SPI flash on some variants;
  GPIO 33–37 likewise for octal PSRAM. If your variant has those,
  binding to them will brick the board until reflashed.
- Safe defaults on most variants: GPIO 1–10, 11–14, 21.

## Memory footprint

- genome + palette: ~4 KB
- two grid arenas (14×14): ~400 B
- bindings table: ~640 B
- Total static: ~5 KB out of 320 KB free DRAM. Trivial.

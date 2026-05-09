# esp32_s3_128_displaytest

Bare-minimum ST7735S 128×128 sanity demo for ESP32-S3 SuperMini.
No PSRAM, no WiFi, no GA — just the display.

```
pio run -t upload
pio device monitor
```

## Wiring (matches the cellular firmware)

| signal | GPIO |
|--------|------|
| SCK    | 12   |
| MOSI   | 11   |
| DC     | 4    |
| CS     | 5    |
| RST    | 6    |
| BL     | 7    |

VCC → 3V3, GND → GND.

## Reading the result

The Serial monitor prints what stage the firmware is on. Watch the
panel as each stage fires:

| symptom                                | likely cause                         |
|----------------------------------------|--------------------------------------|
| stays uniform white through every fill | RST/CS/DC mis-wired, or 3V3 missing  |
| RED fill looks cyan, GREEN looks magenta | panel is BGR — try `INITR_BLACKTAB`  |
| corners on the wrong sides             | wrong `setRotation()` value          |
| flickers / random pixels               | SPI clock too high — leave at 8 MHz  |
| nothing on screen but backlight glows  | INITR variant wrong (try MINI160x80) |

If this demo works but the full `esp32_s3_128/` cellular firmware
does not, suspect either `tft.invertDisplay(true)` or
`tft.setSPISpeed(27_000_000)` in that firmware's `setup()`.

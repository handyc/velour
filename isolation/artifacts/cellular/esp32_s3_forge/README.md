# esp32_s3_forge

Wireworld K=4 hex CA running on an **ESP32-S3 SuperMini** as a
configurable hardware filter. ADC reads on GPIO1 set the input
pulse rate; head events at the output cell drive GPIO2.

This is the firmware companion to the `forge/` Velour app. Evolve a
circuit in the browser → export as a 256-hex grid → paste over UART
to the running firmware → the same circuit now runs on the metal at
20 kHz step rate (max pulse rate ~6.7 kHz).

## Wiring

```
GPIO1  ── input audio / signal source           (ADC1_CH0, 0..3.1V)
GPIO2  ── output: digital pulse train
   |
   ├── 1 kΩ ──┬── 100 µF ── 33 Ω ── headphone tip
   |         |
   |       10 nF
   |         |
   └─────────┴── GND ── headphone sleeve
```

The 1 kΩ + 10 nF is a ~16 kHz low-pass (RC reconstruction). The
100 µF blocks DC into the headphone. The 33 Ω limits current —
without it you can drive the GPIO too hard into a low-impedance can.

`GPIO15` is the onboard LED, blinks at ~1 Hz so you know the
firmware is alive.

## Build & flash

```sh
cd isolation/artifacts/cellular/esp32_s3_forge/
pio run -t upload && pio device monitor
```

The supermini has 4 MB flash (not 8 MB) — `platformio.ini` sets
`board_upload.flash_size = 4MB` so the bootloader's partition table
matches. Without that override the firmware boot-loops on
`do_core_init`.

## Serial console

After connecting at 115200 baud you'll see:

```
esp32_s3_forge — wireworld 16x16 hex CA
step rate 20000 Hz, max pulse 6666 Hz, ADC=GPIO1, OUT=GPIO2
ready. send STATS / GRID / PORTS / STOP / RUN / RESET
```

Commands:

| command | what it does |
|---|---|
| `STATS` | prints ticks, current input period, head count, port positions |
| `GRID` | dumps the current 16×16 grid as 256 hex digits (one per cell, 0-3) |
| `GRID <256-hex>` | replaces the grid (use this to load an evolved circuit) |
| `PORTS <ix> <iy> <ox> <oy>` | moves the input + output ports |
| `STOP` / `RUN` | pauses / resumes the timer |
| `RESET` | reinstalls the default passthrough wire |

## Quick PoC: hear a 1 kHz tone

1. Drive GPIO1 with a 1 kHz square wave (555 timer or signal generator) at 0-3.1V amplitude.
2. The ADC reads ~half scale on average; rate-encoded as ~1500 Hz pulse train.
3. The default passthrough wire propagates the pulses across the 16×16 hex grid (~11 cells × 50 µs/cell ≈ 0.55 ms latency).
4. GPIO2 toggles HIGH on every output head, producing a square wave at the output rate.
5. RC-filtered into headphones, you hear a tone.

Send `STATS` over serial every second to see `head_count` track the
output pulse rate.

## Loading a circuit from Forge

In the Velour `forge` app, open a circuit's detail page and use
**Download for ESP** (in development) — that gives you a paste-ready
`GRID <hex>` line for the serial console. Paste it, hit enter, and
the firmware swaps to your evolved circuit without restarting the
timer.

## Step-rate budget

Per step on a 16×16 hex grid using a flat 16 KiB lookup:

- Read 6 neighbours: ~12 LDR cycles
- Compose 14-bit index: ~6 ALU cycles
- Lookup + write: ~3 cycles
- × 256 cells = ~5400 cycles ≈ 22 µs at 240 MHz

So the 20 kHz target (50 µs/tick) leaves ~28 µs of slack per tick
for ADC sampling, GPIO writes, and serial polling. Could go to
40 kHz step rate (max pulse rate ~13 kHz) by trimming the slack —
useful if you want to filter higher audio frequencies.

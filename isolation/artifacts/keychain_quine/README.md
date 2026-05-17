# keychain_quine — ESP32-S3 pocket-DB keychain firmware

Tiny Arduino-on-ESP32-S3 sketch that embeds one 16 KB class-4 quine
seed in flash and serves it over USB-CDC to a host running
`manage.py keychain sync`.

## What it does

On boot, prints a one-line banner identifying itself + the seed's
sha256. Then waits for commands on USB-CDC:

| Host sends    | Device replies                                              |
| ------------- | ----------------------------------------------------------- |
| `HELLO\n`     | `OK sha=<hex64> size=16384\n` followed by 16,384 raw bytes  |
| `SHA\n`       | `OK sha=<hex64>\n`                                          |
| `PING\n`      | `PONG\n`                                                    |
| `BYE\n`       | `OK\n`                                                      |

That's the whole protocol. No CA simulation runs on-device — the host
does the chain walk + stream generation, which is faster anyway (see
`spoeqi/keychain.py` for the architectural reason).

## Build / flash

Drop your seed at `data/seed.bin` (must be exactly 16,384 bytes), then:

```
pio run -t upload
pio device monitor    # watch the boot banner
```

To get a seed from the Velour DB:

```
manage.py shell -c "from caformer.models import ComponentChampion as C; \
    open('isolation/artifacts/keychain_quine/data/seed.bin','wb').write(\
        bytes(C.objects.get(pk=110).rules_blob))"
```

Quine #110 is the recommended choice: 64 distinct chain levels, 41
consecutive class-4 levels, no cycle within the default depth.

## Host pairing

```
manage.py keychain sync
```

Auto-detects the USB-CDC port, reads the seed, verifies the sha256
matches what the device reported, registers a keychain entry, and
prepares the 16 MB DB for browsing.

## Hardware notes

- Designed for ESP32-S3 with the built-in USB-Serial-JTAG. SuperMini
  boards work out of the box. No external UART bridge needed.
- USB power is plenty; the firmware draws under 50 mA.
- Cold-boot to first banner byte is ~300 ms.
- Single CA at a time fits trivially in internal SRAM. PSRAM is unused
  and not required.

## Footprint

- Flash: ~80-120 KB compiled (Arduino+CDC overhead) + 16 KB seed.
- RAM: ~12 KB heap, 4 KB stack. Well under 5% of the 520 KB on-chip.

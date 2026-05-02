# xcc_addon — drop-in /compile-c handler

Tiny Arduino-framework wrapper around the embedded xcc700 compiler.
Mounts a `POST /compile-c` route on a caller-provided `WebServer` so
any firmware that already runs an HTTP server gains C-source-to-ELF
compilation in one round trip.

## Use

```cpp
#include "xcc_addon.h"

WebServer server(80);

void setup() {
    // ...your existing routes...
    xcc_addon_mount(server);   // adds POST /compile-c
    server.begin();
}
```

## /compile-c protocol

```
POST /compile-c                         body: C source (raw)
  → 200 OK  application/octet-stream    body: Xtensa-LX7 ELF
  ← 400     text/plain                  body: compile error message
```

With `?slot=NAME`:
```
POST /compile-c?slot=fitness            body: C source
  → 200 OK  text/plain   "OK compiled+patched slot=fitness ..."
  ← 501                  if no slot patcher registered (call
                         xcc_addon_set_slot_patcher first)
```

## Wired into

| target | LOC | endpoint | slot patcher |
|---|---:|:---|:---|
| `hex_ca_class4/esp32_s3_xcc/`     | 1100 | bespoke `handle_compile_c` (Phase 1) | yes — 4 slots |
| `cellular/esp32_s3/`              |  920 | `xcc_addon_mount(server)` | not yet |
| `cellular/esp32_s3_128/`          |  920 | `xcc_addon_mount(server)` | not yet |
| `hexnn_search/esp32_s3_tft/`      |  606 | `xcc_addon_mount(server)` | not yet |

## Targets where xcc is *available* but no endpoint mounted

These have no WiFi/HTTP today; the xcc compiler is linked in via
`build_src_filter` so `xcc_compile()` is callable from anywhere in
the firmware (e.g. on a button press, from a serial-arrived blob,
or as a future on-device GA mutator).

- `hex_ca_class4/esp32_s3_full/`
- `hex_ca_class4/esp32_s3_gpio/`
- `hex_ca_class4/esp_st7735s/` (esp32s3 env only — esp8266 is
  Xtensa LX106, not LX7, so the ELFs xcc emits won't run)
- `hexnn_search/esp32_s3/`
- `oneclick_class4/esp32_s3/`

If you want `/compile-c` on any of these, the work is: add WiFi+
WebServer to the firmware, then `xcc_addon_mount(server)`. The
basis fork `esp32_s3_xcc/` is the canonical reference — copy its
`try_connect_sta` / `start_ap_fallback` block.

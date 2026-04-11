# velour_client — ESP telemetry drop-in

Header-only-style mini-library (actually `.h` + `.cpp` for compile-unit
sanity) that lets any ESP8266 or ESP32 sketch report sensor readings to
a velour instance over HTTP. Add it to an **existing working `.ino`**
without rewriting anything — it's additive, not a replacement firmware.

## Files

- `velour_client.h`   — public interface
- `velour_client.cpp` — implementation
- `velour_example.ino` — minimal standalone example sketch

## Installation (one-time per device)

1. In velour: go to **Fleet → &lt;your node&gt;** and copy the **slug** (e.g.
   `gary`) and the **API token** from the detail page.
2. In Arduino IDE: open your existing sketch for the device (or the
   example sketch here for a new one).
3. Copy `velour_client.h` and `velour_client.cpp` into the sketch folder
   so they sit next to your `.ino`.
4. At the top of your sketch, add `#include "velour_client.h"`.
5. Create a `VelourClient` instance at file scope:
   ```cpp
   VelourClient velour(
       "http://velour.lucdh.nl",           // base URL, no trailing slash
       "gary",                              // slug
       "PASTE-YOUR-48-CHAR-TOKEN-HERE"      // api_token
   );
   ```
6. In `loop()` (or wherever your existing sensor reads happen), queue
   readings and periodically flush:
   ```cpp
   velour.addReading("temp_c", myTempC);
   velour.addReading("humidity", myHumidity);
   if (timeToReport()) {
       velour.report();
   }
   ```
7. Reflash the device, open the serial monitor, verify you see
   `velour report: HTTP 200` after boot.
8. On the velour fleet page, the node's card should now show a green
   **online** border and a "Recent Telemetry" section should appear on
   the node detail view within a minute.

## What the client sends

Each `report()` call POSTs a small JSON body to
`<base-url>/api/nodes/<slug>/report/`:

```json
{
  "readings": [
    {"channel": "temp_c",         "value": 22.1875},
    {"channel": "humidity",       "value": 58.42},
    {"channel": "soil_moisture",  "value": 33.0}
  ],
  "firmware_version": "gary-0.3.0",
  "free_heap":        234560,
  "uptime_ms":        184523,
  "rssi":             -63
}
```

Auth is `Authorization: Bearer <token>`. Failure modes:

- `401` — wrong or missing token (ESP probably has a stale one).
- `403` — node is disabled in velour.
- `404` — no such slug.
- `400` — malformed JSON body.
- `200` — stored, returns `{"ok":true, "stored":N, "node":"<slug>"}`.

## Heartbeats

Calling `velour.report()` with no pending readings is a valid heartbeat —
velour updates `last_seen_at` and `last_ip` but stores zero rows. Useful
for very-low-data nodes that just want to prove they're alive.

## What it does NOT do

- No HTTPS. Yet. Plain HTTP only — fine on a trusted LAN, add TLS before
  exposing velour to the public internet.
- No retry queue. A failed `report()` drops its pending batch so memory
  can't grow unbounded during a long network outage.
- No OTA update path. Use ArduinoOTA separately if you want remote
  reflashing.
- No commands-back-from-velour. That comes in a later phase; v1 is
  strictly "ESP pushes, velour stores."
- No decision-tree inference. That's Phase 3.

## License

Same as velour.

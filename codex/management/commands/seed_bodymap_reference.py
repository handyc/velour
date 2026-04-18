"""Seed a short Codex manual documenting the Bodymap subsystem.

Exercises the publishing-house additions end-to-end:

  - Editions metadata (edition, ISBN-like, publisher, copyright, license)
    drives the colophon page.
  - Bibliography (BibTeX) + `[@key]` citations render a References
    section and inline author-year labels.
  - A Graphviz figure exercises the Kroki path; a raw SVG figure
    exercises the local cairosvg branch.
  - Seven sections fill out the 10–15 page "short" format target.

Idempotent: re-running replaces the existing manual's body wholesale,
so content edits land cleanly. Figures are regenerated from source.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from codex.models import Figure, Manual, Section


SLUG = 'bodymap-reference'


BIBLIOGRAPHY = r"""
@manual{atmel_attiny85,
  author    = {{Atmel Corporation}},
  title     = {ATtiny25/45/85 Datasheet},
  year      = {2016},
  publisher = {Atmel},
  note      = {Rev. 2586Q-AVR-08/2013},
}

@manual{atmel_attiny13a,
  author    = {{Atmel Corporation}},
  title     = {ATtiny13A Datasheet},
  year      = {2017},
  publisher = {Atmel},
  note      = {Rev. 8126H-AVR-04/2016},
}

@manual{nxp_i2c,
  author    = {{NXP Semiconductors}},
  title     = {UM10204: I2C-bus specification and user manual},
  year      = {2021},
  publisher = {NXP},
  note      = {Rev. 7.0},
}

@manual{espressif_s3,
  author    = {{Espressif Systems}},
  title     = {ESP32-S3 Technical Reference Manual},
  year      = {2023},
  publisher = {Espressif},
}

@book{tufte_envisioning,
  author    = {Tufte, Edward R.},
  title     = {Envisioning Information},
  publisher = {Graphics Press},
  address   = {Cheshire, Connecticut},
  year      = {1990},
}
""".strip()


SECTIONS = [
    {
        'title': 'Overview',
        'body': """
Bodymap is Velour's wearable mesh. Each node is an ESP-family MCU
sewn onto a garment or strapped to a limb; the fleet reports motion
telemetry to the Velour server, which clusters sibling nodes into
body segments (left forearm, right shin, etc.) by correlation.

The architecture is intentionally boring: no custom radio, no novel
protocol. Every node runs the same firmware image; per-node
behaviour is declared server-side and fetched on boot. This keeps
OTA updates atomic across the fleet and lets operators reconfigure
sensors without touching a soldering iron.

!fig:fleet-topology

The node classes are:

- **Wearable** — motion-reporting ESP8266 / ESP32-S3, 100 Hz IMU.
- **HUD** — ESP32-S3 driving an SSD1306 OLED on a beamsplitter;
  paints time, mood, and open concerns pulled from Identity.
- **Visor** — Raspberry Pi headgear; reads a compiled Aether world
  manifest and renders to dual eye displays via KMS/DRM.

Node counts and roles are fluid. The server is the source of truth
for which node sits where on the body.
""".strip(),
        'sidenotes': (
            '100 Hz matches the GY-95T IMU\'s advertised native rate.\n'
            'Clustering math cares about consistent cadence, not raw speed.'
        ),
    },
    {
        'title': 'Wearable Nodes',
        'body': """
A wearable is the smallest useful Bodymap node. Current fleet:

- **ESP32-S3 SuperMini (4 MB flash)** — preferred for new builds.
  Native USB, more RAM than the '8266 has any right to, dual-core
  leaves plenty of headroom above the 18 % baseline.
- **ESP8266 (NodeMCU)** — legacy but still flying. Single-core,
  softUART sensors refuse to come up on these but the firmware
  keeps them in the registry with a 0.0 default reading so the
  channel column still appears in reports.

Every wearable carries a GY-95T IMU over Serial1 at 115200 baud
[@espressif_s3, pp. 327–344]. The firmware samples at 100 Hz and
batches a report every 500 ms — five IMU windows per packet, which
is enough detail for the motion-clustering correlator.

Provisioning is mac-based: on first boot the firmware posts its
MAC to `/nodes/register/` and the server either matches it to a
known `Node` row or creates a new one. The returned JSON carries
the slug, api token, and base URL that the node caches to LittleFS.
""".strip(),
        'sidenotes': (
            'See `nodes.views.api_register` for the registration handshake.\n'
            'The LittleFS cache is what lets a node reboot offline.'
        ),
    },
    {
        'title': 'Firmware Layers',
        'body': """
One firmware, three libraries, a thin `main.cpp`.

- **velour_client** — HTTPClient wrapper. Owns the bearer token,
  the LittleFS cache of credentials and last-known configs, and
  OTA (`checkForUpdate` fetches `/nodes/firmware/<slug>.bin`).
- **motion** — IMU sampling (`motion_buffer`), node-to-node
  correlation (`motion_net`), and cluster membership
  (`motion_cluster`). Pure math, no I/O.
- **sensors** — the per-channel peripheral layer described in the
  next section.

`main.cpp` is the control loop:

1. Connect WiFi, register, pull config.
2. `sensors.loadFromJson(configJson)` — hand-rolled parser, no
   ArduinoJson dependency.
3. Enter the 500 ms report tick: sample IMU, step motion math,
   sample each configured sensor, build the reading batch, POST
   to `/bodymap/api/segment/` or `/nodes/api/report/`.

The entire firmware fits in 74.5 % of the S3 SuperMini's 4 MB
flash with a healthy 18 % RAM baseline. Room to grow.
""".strip(),
        'sidenotes': (
            'Building: `pio run -e esp32-s3-supermini` in `bodymap_firmware/`.',
        )[0],
    },
    {
        'title': 'The Sensor Registry',
        'body': """
`SensorRegistry` is the per-channel abstraction. A `Sensor` is a
virtual base with one virtual method — `float sample()` — and five
concrete subclasses, one per supported peripheral kind:

- **digital** — `digitalRead()` with optional pull-up/down and
  active-low inversion.
- **analog** — `analogRead()` averaged over N samples, with scale
  and offset applied.
- **attiny_i2c** — `Wire` request to an ATtiny85 acting as a USI
  I2C slave [@atmel_attiny85, §16]. Common for daisy-chaining
  sensors that don't have a native I2C interface.
- **attiny_pwm** — `pulseIn()` on a GPIO reading the duty cycle of
  a '13a PWM output [@atmel_attiny13a]. Minimal ATtiny code
  footprint; good for single-axis analog readings.
- **attiny_softuart** — `HardwareSerial` RX from a '13a
  bit-banging 0xA5 / hi / lo frames at 1200 baud. Slow but
  flash-trivial on the tiny side.

Channels are declared on the server (see *Channel Configuration*
below). The registry is built at boot from the JSON manifest;
misconfigured entries (missing pin, out-of-range I2C address) are
skipped with a Serial log line, not silently hidden.
""".strip(),
        'sidenotes': (
            'The five kinds are intentional — resist adding a sixth '
            'without a clear separation.\nATtiny slaves keep the "one big '
            'MCU, many small ones" pattern explicit.'
        ),
    },
    {
        'title': 'Server API',
        'body': """
Four endpoints carry the fleet's traffic, all bearer-authenticated.

!fig:segment-packet

- `POST /bodymap/api/segment/` — the node reports its clustered
  role assignment. Body: `{slug, role, confidence}`. Idempotent
  on `node`; a second call updates the existing `Segment` row.
  When the row is `operator_locked`, the server silently succeeds
  with `locked: true` so the firmware stops retrying.
- `GET /bodymap/api/config/<slug>/` — the node fetches its
  `NodeSensorConfig.channels`. Response includes an `updated_at`
  field the firmware uses for cache invalidation.
- `GET /bodymap/api/hud/<slug>/` — short payload for an OLED HUD
  node: time, date, mood, and up to three short lines drawn from
  Identity (latest Tick, open Concern count, etc.).
- `POST /nodes/api/report/` — the generic telemetry endpoint
  shared with the rest of the fleet; Bodymap readings land here
  alongside Aquarium and Weather data.

Bearer auth uses `hmac.compare_digest`. Not `==`. The three-line
preamble (slug lookup, enabled check, token compare) is
duplicated across endpoints; a `@require_node_bearer` decorator is
on the cleanup list.
""".strip(),
        'sidenotes': (
            'A locked Segment is the operator saying "stop reclassifying '
            'this one, I\'ve told you what it is".'
        ),
    },
    {
        'title': 'ATtiny Slaves',
        'body': """
ATtinys sit between an ESP and the physical sensor. The ESP stays
clean; the tiny does one job in 1 KB of flash. Three template
families ship in `bodymap/attiny_sources/`:

- `usi_i2c_slave_*` — USI-mode I2C slave on the '85. Seven-bit
  address + one register read returning two bytes [@nxp_i2c].
  Common victims: photoresistor, thermistor, single-axis analog.
- `pwm_*` — Timer0 fast-PWM on the '13a. The ESP side uses
  `pulseIn()` and interprets duty cycle as a normalized reading.
- `softuart_tx_13a.c` — 1200-baud bit-banged UART TX at 134
  bytes total. Sends 0xA5 / hi / lo frames on a single GPIO; the
  ESP side uses a `HardwareSerial` RX for clean framing.

The companion `attiny_workshop` at `/bodymap/attiny/` lets
operators fork any template, edit in-browser, and build via
`avr-gcc` without leaving the web UI. A pure-JS t13a emulator
runs unit tests on the tiny code before it ever touches silicon.
""".strip(),
        'sidenotes': '',
    },
    {
        'title': 'Channel Configuration',
        'body': """
`NodeSensorConfig` is a `OneToOne` on `Node`. Its `channels`
`JSONField` is a list of per-channel dicts with a `kind` string
and kind-specific fields. The operator-facing wizard at
`/bodymap/config/<slug>/` renders one row per channel with a kind
picker that toggles which fields are visible.

A typical two-channel config:

    [
      {"kind": "digital", "channel": "button_a",
       "pin": 4, "pull": "up", "active_low": true},
      {"kind": "attiny_i2c", "channel": "thumb_flex",
       "addr": 42, "bytes": 2, "scale": 0.001, "offset": 0.0}
    ]

The firmware re-fetches the config at boot and caches it to
LittleFS, so nodes come up with their last-known layout even if
the server is unreachable. The cache is byte-compared before
writing to avoid flash-wear on identical configs. Versioning is
via `updated_at` in the response; the wizard commits atomically so
partial reads are impossible.

For a broader essay on the Tufte-influenced layout choices on the
wizard page, see [@tufte_envisioning].
""".strip(),
        'sidenotes': (
            'LittleFS cache path: `/velour/sensor_config.json`.'
        ),
    },
]


FIGURES = [
    {
        'section_slug': 'overview',
        'slug': 'fleet-topology',
        'kind': 'graphviz',
        'caption': 'Fleet topology. Wearable nodes flow telemetry to the '
                   'Velour server; HUD and visor nodes consume derived '
                   'state (Identity, Aether world manifests).',
        'caption_position': 'margin',
        'source': """
digraph G {
    rankdir=LR;
    node [shape=box, style="rounded,filled", fillcolor="#f6f8fa",
          color="#30363d", fontname="Helvetica", fontsize=10];
    edge [color="#6e7681", fontsize=9, fontname="Helvetica"];

    wearable [label="Wearable\\n(ESP32-S3 / ESP8266)"];
    hud      [label="HUD\\n(ESP32-S3 + OLED)"];
    visor    [label="Visor\\n(Raspberry Pi)"];
    velour   [label="Velour Server", fillcolor="#ddf4ff"];
    identity [label="Identity", fillcolor="#fff8c5"];
    aether   [label="Aether", fillcolor="#fff8c5"];

    wearable -> velour [label="/bodymap/api/segment/"];
    velour   -> wearable [label="/bodymap/api/config/"];
    hud      -> velour [label="/bodymap/api/hud/"];
    velour   -> identity [style=dashed];
    velour   -> aether [style=dashed];
    aether   -> visor [label="/aether/*/visor.json"];
}
""".strip(),
    },
    {
        'section_slug': 'server-api',
        'slug': 'segment-packet',
        'kind': 'svg',
        'caption': 'Anatomy of a segment report POST. Bearer auth in the '
                   'header; body is one JSON object with three required '
                   'fields and an optional confidence.',
        'caption_position': 'below',
        'source': """
<svg xmlns="http://www.w3.org/2000/svg" width="440" height="180" viewBox="0 0 440 180">
  <style>
    text { font-family: ui-monospace, Menlo, monospace; font-size: 11px; fill: #24292f; }
    .lbl  { font-size: 9px; fill: #6e7681; }
    .box  { fill: #f6f8fa; stroke: #30363d; stroke-width: 1; }
    .hdr  { fill: #ddf4ff; stroke: #0969da; stroke-width: 1; }
    .body { fill: #fff8c5; stroke: #bf8700; stroke-width: 1; }
  </style>

  <rect class="hdr" x="10" y="20"  width="420" height="22"/>
  <text x="20" y="36">POST /bodymap/api/segment/  HTTP/1.1</text>

  <rect class="hdr" x="10" y="46"  width="420" height="22"/>
  <text x="20" y="62">Authorization: Bearer 7f2a…c41</text>

  <rect class="hdr" x="10" y="72"  width="420" height="22"/>
  <text x="20" y="88">Content-Type: application/json</text>

  <rect class="body" x="10" y="104" width="420" height="60"/>
  <text x="20" y="122">{"slug":       "bodymap-aabbcc",</text>
  <text x="20" y="138"> "role":       "forearm_l",</text>
  <text x="20" y="154"> "confidence": 0.87}</text>

  <text class="lbl" x="10" y="14">request line</text>
  <text class="lbl" x="10" y="104" dy="-2">JSON body</text>
</svg>
""".strip(),
    },
]


class Command(BaseCommand):
    help = 'Seed the Bodymap Reference short manual.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force', action='store_true',
            help='Replace the existing manual\'s sections/figures.',
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        manual, created = Manual.objects.get_or_create(
            slug=SLUG,
            defaults=dict(
                title='Bodymap Reference',
                subtitle='The wearable mesh, end to end',
                format='short',
                author='Velour',
                version='1.0',
                abstract=(
                    'A short reference to the Bodymap subsystem: its node '
                    'classes, firmware layers, sensor registry, and the '
                    'server API that binds them. Ten pages, seven sections.'
                ),
                bibliography=BIBLIOGRAPHY,
                edition='First edition',
                publisher='Velour Press',
                publisher_city='Leiden, Netherlands',
                copyright_year='2026',
                copyright_holder='C. A. Handy',
                license='CC BY-SA 4.0',
            ),
        )

        if not created and not opts['force']:
            self.stdout.write(
                self.style.WARNING(
                    f'Manual {SLUG!r} already exists; pass --force to replace '
                    f'its sections and figures.'
                )
            )
            return

        if not created:
            manual.sections.all().delete()
            manual.bibliography = BIBLIOGRAPHY
            manual.edition = 'First edition'
            manual.publisher = 'Velour Press'
            manual.publisher_city = 'Leiden, Netherlands'
            manual.copyright_year = '2026'
            manual.copyright_holder = 'C. A. Handy'
            manual.license = 'CC BY-SA 4.0'
            manual.save()

        for i, sec in enumerate(SECTIONS):
            Section.objects.create(
                manual=manual,
                title=sec['title'],
                body=sec['body'],
                sidenotes=sec['sidenotes'],
                sort_order=i + 1,
            )

        sections_by_slug = {s.slug: s for s in manual.sections.all()}
        for i, fig in enumerate(FIGURES):
            section = sections_by_slug[fig['section_slug']]
            Figure.objects.create(
                section=section,
                slug=fig['slug'],
                kind=fig['kind'],
                source=fig['source'],
                caption=fig['caption'],
                caption_position=fig['caption_position'],
                sort_order=i + 1,
            )

        self.stdout.write(self.style.SUCCESS(
            f'Seeded manual {SLUG!r}: '
            f'{manual.sections.count()} sections, '
            f'{sum(s.figures.count() for s in manual.sections.all())} figures.'
        ))

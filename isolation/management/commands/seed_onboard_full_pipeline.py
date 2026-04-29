"""Seed the Isolation `hex-ca-onboard-full` pipeline.

The maximally consolidated form: hunt + display + GPIO drive on a
single S3 SuperMini binary. Sibling of:
  - oneclick-hex-class4   (hunt only)
  - hex-ca-class4         (display only)
  - hex-ca-gpio-actuator  (GPIO only)

Origin: esp32_s3 — the only platform with the SRAM, USB, broken-out
GPIO, AND parallel-bus headroom to do all three concurrently. Every
other target is either too small (no room for population + display
buffers) or too large (Pi 4 doesn't add anything for this scope).

Run:
    venv/bin/python manage.py seed_onboard_full_pipeline
Reset:
    venv/bin/python manage.py seed_onboard_full_pipeline --reset
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from isolation.models import IsolationTarget, Pipeline, Stage


SLUG = 'hex-ca-onboard-full'

PIPELINE = {
    'slug': SLUG,
    'name': 'Hex-CA on-board full pipeline',
    'apps_used': 'det, automaton',
    'origin_target': 'esp32_s3',
    'description':
        'Single S3 binary that hunts a class-4 ruleset, then runs '
        'the winner with simultaneous ST7735S TFT visualisation and '
        'cell→GPIO output binding. Boot sequence: GA on bootstrap '
        'genome → save winner → loop forever stepping the CA, '
        'rendering pixels, and driving pins. Reset = re-hunt. The '
        'maximally consolidated form of the entire Velour CA story.',
    'notes':
        'Combines the algorithms from oneclick-hex-class4 (hunt), '
        'hex-ca-class4 (display), and hex-ca-gpio-actuator (GPIO). '
        'Peak RAM during hunt is ~156 KB on a 320 KB DRAM budget; '
        '~120 KB of that is the GA population which goes idle after '
        'the run phase begins. Adding the TFT libraries on top of '
        'the hunter cost ~5 KB RAM. TFT pin map (SCK 12, MOSI 11, '
        'DC 4, CS 5, RST 6, BL 7) constrains GPIO output choices '
        'to non-conflicting pins (default 1, 2, 3, 8). Winner '
        'persisted as /winner.bin in the same hunter-tail format as '
        'oneclick_class4/hunter.c, so it can be pulled off-device '
        'and dropped into the Linux engine.',
}

STAGES = [
    {
        'order': 1, 'app_label': 'det',
        'entrypoint': 'pipeline.run_oneclick_pipeline',
        'produces': 'top winner palette + 4096-byte packed genome',
        'fields_used': 'population_size\ngenerations\ngrid_seed',
        'notes': 'Hunt phase — same GA as oneclick-hex-class4 stage 1, '
                 'with TFT progress bar tied to best-fitness colour.',
    },
    {
        'order': 2, 'app_label': 'automaton',
        'entrypoint': 'detector.step_packed',
        'produces': 'next-tick grid (14×14 hex)',
        'fields_used': '',
        'notes': 'Same engine as both display and GPIO sketches. Ticks '
                 'at TICK_MS cadence; default 300 ms (3 Hz).',
    },
    {
        'order': 3, 'app_label': 'automaton',
        'entrypoint': 'render.draw_cell',
        'produces': 'TFT pixels (ST7735S 80×160 landscape)',
        'fields_used': 'palette (4 ANSI-256 indices → RGB565)',
        'notes': 'Diff-render: only redraw cells whose value changed '
                 'since the previous tick. Keeps SPI bus quiet so the '
                 'inner loop stays smooth even when the CA is busy.',
    },
    {
        'order': 4, 'app_label': 'automaton',
        'entrypoint': 'gpio.apply_bindings',
        'produces': 'GPIO pin levels',
        'fields_used': 'cell_x\ncell_y\ngpio_pin\nstate_mask',
        'notes': 'Terminal stage. Per-tick: for each binding, '
                 'level = (mask >> cell_value) & 1, write to pin. '
                 'Bindings live in /gpio_map.txt; default 4 pins on '
                 'GPIO 1/2/3/8 watching cells (3,5)..(6,5).',
    },
]


# (target, status, artifact_path, size_bytes, notes)
TARGETS = [
    ('cli_oneliner', 'infeasible', '', None,
     'Hunt + display + GPIO drive in 80 chars is conceptually '
     'impossible.'),
    ('c_compact', 'infeasible', '', None,
     'No display + GPIO at compact-C scope without enormous library '
     'pull-in. Hunt-only fits in compact C; full pipeline does not.'),
    ('attiny13a', 'infeasible', '', None,
     '1 KB flash, 64 B RAM. Genome alone exceeds the device. '
     'Infeasible at any scope.'),
    ('attiny85', 'infeasible', '', None,
     '8 KB flash, 512 B RAM. Cannot fit GA population in 512 B '
     'SRAM. Infeasible.'),
    ('esp8266', 'infeasible', '', None,
     '~80 KB SRAM. The GA population alone is 120 KB — exceeds '
     'available RAM by a factor of 1.5. Hunt would have to use a '
     'smaller population (POP=8?), display + GPIO would fit but '
     'the integrated story breaks down.'),
    ('esp32', 'not_started', '', None,
     'Original ESP32 has ~320 KB SRAM — same DRAM budget as the S3 '
     'in Arduino-on-ESP32. Should work; not attempted because the '
     'S3 is the chosen target. Same source should compile after '
     'swapping pin map and removing -DARDUINO_USB_MODE flag.'),
    ('esp32_s3', 'not_started',
     'isolation/artifacts/hex_ca_class4/esp32_s3_full/', 316337,
     'Origin platform. Builds clean (RAM 47.6%, Flash 9.5%). '
     'Single binary; LittleFS holds /gpio_map.txt and post-hunt '
     '/winner.bin. Hunt phase ~10-30 s with TFT progress bar; run '
     'phase indefinite at 3 Hz default. Desk-built and link-verified; '
     'awaiting first flash. Bump to "working" after a hunt + run '
     'cycle completes on hardware with visible TFT output and '
     'measurable GPIO toggling.'),
    ('pi4', 'not_started', '', None,
     'Pi 4 expansion: adds nothing structurally over the S3 (more '
     'RAM, slower GPIO, harder to integrate physically). Plausible '
     'as a reference but low priority.'),
]


class Command(BaseCommand):
    help = 'Seed the Isolation hex-ca-onboard-full pipeline.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
            help='Delete any existing rows for this pipeline first.')

    def handle(self, *args, **opts):
        if opts['reset']:
            n, _ = Pipeline.objects.filter(slug=SLUG).delete()
            self.stdout.write(f'  reset: deleted {n} existing objects')

        pipeline, created = Pipeline.objects.update_or_create(
            slug=PIPELINE['slug'],
            defaults={k: v for k, v in PIPELINE.items() if k != 'slug'},
        )
        self.stdout.write(
            f'{"+" if created else "~"} pipeline: {pipeline.slug}')

        for s in STAGES:
            Stage.objects.update_or_create(
                pipeline=pipeline, order=s['order'],
                defaults={k: v for k, v in s.items() if k != 'order'},
            )
        self.stdout.write(f'  {len(STAGES)} stages')

        pipeline.ensure_all_targets()

        for target_key, status, path, size, notes in TARGETS:
            tgt, _ = IsolationTarget.objects.update_or_create(
                pipeline=pipeline, target=target_key,
                defaults={
                    'status': status,
                    'artifact_path': path,
                    'size_bytes': size,
                    'notes': notes,
                },
            )

        for t in pipeline.targets.all():
            if t.artifact_path and t.size_bytes is None:
                p = Path(t.artifact_path).resolve()
                if p.exists() and p.is_file():
                    t.size_bytes = p.stat().st_size
                    t.save(update_fields=['size_bytes'])

        self.stdout.write(self.style.SUCCESS(
            f'Done. {pipeline.targets.count()} targets on '
            f'{pipeline.slug}.'))

"""Seed the Isolation `hex-ca-gpio-actuator` pipeline.

Sibling of `hex-ca-class4` (display) and `oneclick-hex-class4` (hunt).
Same engine, different terminal stage: instead of rendering the CA to
a TFT or ANSI terminal, individual cells drive GPIO output pins. The
ESP32-S3 SuperMini is the native target — it has the SRAM for the
genome plus enough broken-out GPIOs to be useful as a hardware
sequencer or pattern generator.

Origin: esp32_s3 (the platform this pipeline natively lives on).
Distillations (smaller targets) and expansions (larger targets) both
make sense here:

  - cli_oneliner: infeasible — can't drive GPIO from a shell oneliner.
  - c_compact:    feasible on Pi via /sys/class/gpio sysfs.
  - attiny13a:    infeasible at full ruleset.
  - attiny85:     borderline; would need symmetry-reduced rule.
  - esp8266:      feasible with smaller grid; fewer broken-out GPIOs.
  - esp32:        feasible; preferred over S3 only if you don't need
                  native USB.
  - esp32_s3:     ORIGIN. Working artifact at esp32_s3_gpio/.
  - pi4:          feasible; sysfs gpio or libgpiod, would be the most
                  capable but slowest physically.

Run:
    venv/bin/python manage.py seed_gpio_actuator_pipeline
Reset:
    venv/bin/python manage.py seed_gpio_actuator_pipeline --reset
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from isolation.models import IsolationTarget, Pipeline, Stage


SLUG = 'hex-ca-gpio-actuator'

PIPELINE = {
    'slug': SLUG,
    'name': 'Hex-CA GPIO actuator',
    'apps_used': 'automaton',
    'origin_target': 'esp32_s3',
    'description':
        'Run an evolved hex-CA ruleset in memory and use individual '
        'cells to drive GPIO output pins. Same engine as the display '
        'and hunt pipelines; the terminal stage emits voltages on '
        'pins instead of pixels on a screen. Useful as a hardware '
        'sequencer, pattern generator, or substrate for connecting '
        'CA dynamics to physical actuators (LEDs, relays, motors, '
        'audio gates).',
    'notes':
        'Genome format is the same 4104-byte tail [HXC4 magic + 4 '
        'palette + 4096 packed genome] as oneclick_class4/hunter.c, '
        'so any winner_<N>.bin from a hunt drops in as /genome.bin. '
        'Per-cell→pin bindings live in /gpio_map.txt as one binding '
        'per line: cell_x,cell_y,gpio_pin,state_mask. state_mask is '
        '4-bit (K=4 cell states); bit N set ⇒ pin HIGH when cell '
        'value == N. Origin platform is esp32_s3_supermini; the '
        'pi4 expansion is a future direction (sysfs gpio).',
}

STAGES = [
    {
        'order': 1, 'app_label': 'automaton', 'entrypoint': 'packed.PackedRuleset',
        'produces': '4096-byte packed ruleset (K=4, 16384 situations, 2 bits/output)',
        'fields_used': 'data (bytearray 4096)\npalette (4 bytes)',
        'notes': 'Genome representation; same as the hunt pipeline. '
                 'Loaded from /genome.bin on the device.',
    },
    {
        'order': 2, 'app_label': 'automaton', 'entrypoint': 'detector.step_packed',
        'produces': 'Next-tick grid (list of lists of ints)',
        'fields_used': '',
        'notes': 'Per-tick CA stepper. One memory fetch + bit '
                 'extract per cell per tick.',
    },
    {
        'order': 3, 'app_label': 'automaton', 'entrypoint': 'gpio.apply_bindings',
        'produces': 'GPIO pin levels written',
        'fields_used': 'cell_x\ncell_y\ngpio_pin\nstate_mask (4-bit)',
        'notes': 'Terminal stage. For each binding (cell, pin, mask), '
                 'compute level = (mask >> cell_value) & 1 and write '
                 'it to the pin. No corresponding Velour-side class '
                 'yet — bindings live in /gpio_map.txt on device.',
    },
]


# (target, status, artifact_path, size_bytes, notes)
TARGETS = [
    ('cli_oneliner', 'infeasible', '', None,
     'No way to drive GPIO from a shell oneliner. Conceptually '
     'impossible.'),
    ('c_compact', 'not_started', '', None,
     'Feasible on Pi via /sys/class/gpio sysfs. Engine is already '
     '~14 KB in oneclick_class4/hunter.c; adding GPIO open/write '
     'would push it slightly. Pi-only — sysfs is Linux-specific.'),
    ('attiny13a', 'infeasible', '', None,
     '1 KB flash, 64 B RAM. The 4 KB genome cannot fit on the '
     'device. Infeasible.'),
    ('attiny85', 'infeasible', '', None,
     '8 KB flash, 512 B RAM. Could store one genome in flash but '
     'no way to step a 14×14 grid in 512 B SRAM. Would require a '
     'symmetry-reduced ruleset; deferred.'),
    ('esp8266', 'not_started', '', None,
     'Feasible with smaller grid; ESP8266 exposes ~9 broken-out '
     'GPIOs on a NodeMCU. Same code as esp32_s3 with Arduino '
     'digitalWrite portability. Not attempted.'),
    ('esp32', 'not_started', '', None,
     'Feasible; identical code to esp32_s3 but no native USB CDC. '
     'Not attempted.'),
    ('esp32_s3', 'not_started',
     'isolation/artifacts/hex_ca_class4/esp32_s3_gpio/', 299065,
     'ESP32-S3 SuperMini origin platform. Loads /genome.bin (same '
     '4104-byte tail format as hunter winners) and /gpio_map.txt '
     '(one binding per line: cell_x,cell_y,gpio_pin,state_mask). '
     'TICK_MS compile-time configurable; default 1 Hz, can run '
     'into kHz range. Builds clean (RAM 7.4%, Flash 8.9%). '
     'Desk-built and link-verified; awaiting first flash. Bump to '
     '"working" after pin levels match expectations on hardware.'),
    ('pi4', 'not_started', '', None,
     'Future expansion: pi4.py with libgpiod or /sys/class/gpio. '
     'Slowest physically (Linux scheduling jitter, sysfs overhead) '
     'but most flexible.'),
]


class Command(BaseCommand):
    help = 'Seed the Isolation hex-ca-gpio-actuator pipeline.'

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

"""Seed Isolation with the hex-CA pipeline (Det → Evolution → Automaton).

This is the first concrete pipeline we want to re-package as a
minimum-viable, multi-target artifact set. The seed defines the
stages and leaves every platform target at `not_started` with a
stub — filling them in is the hand-craft part of isolating.

Run with:
    venv/bin/python manage.py seed_isolation
Reset + reseed:
    venv/bin/python manage.py seed_isolation --reset
"""

from django.core.management.base import BaseCommand

from isolation.models import IsolationTarget, Pipeline, Stage


HEX_CA_SLUG = 'hex-ca-class4'

HEX_CA_PIPELINE = {
    'slug': HEX_CA_SLUG,
    'name': 'Hex-CA class-4 search',
    'apps_used': 'det, evolution, automaton',
    'description': (
        'Brute-force search for 4-colour hexagonal cellular-automaton '
        'rulesets that exhibit Wolfram class-4 behaviour (Rule 110-'
        'analog on hex grids), then breed the survivors and render '
        'them. Det runs the search; Evolution Engine mutates the best '
        'candidates; Automaton runs the ruleset visually so a human '
        'can decide whether the behaviour is genuinely class-4.'
    ),
    'notes': (
        'Isolation targets:\n'
        '  - trim Candidate to {ruleset_hex, score, seed, generations}\n'
        '  - drop Evolution meta/meta-meta levels; keep only L0\n'
        '  - Automaton renderer reduces to a frame loop on a hex grid\n'
        '  - shared state is a single packed ruleset string per run\n'
        '\n'
        'Branching notes live on the stages below.'
    ),
}

HEX_CA_STAGES = [
    {
        'order': 1,
        'app_label': 'det',
        'entrypoint': 'det_search  (management command)',
        'produces': 'SearchRun + Candidate rows',
        'fields_used': (
            'SearchRun: seed, rules_tested, started_at\n'
            'Candidate: ruleset_hex, score, seed, generations\n'
            '— everything else on SearchRun/Candidate is admin chrome'
        ),
        'notes': (
            'Hex neighbourhood=6, 4 colours ⇒ 4^(4^6) rulesets. '
            'Search is stochastic; seed is the only knob that matters.'
        ),
    },
    {
        'order': 2,
        'app_label': 'evolution',
        'entrypoint': 'evolve_lut  (management command, -- tt from Det)',
        'produces': 'Breeding population seeded from Det winners',
        'fields_used': (
            'Agent: genes_json (LUT bitstring), fitness\n'
            '— L1/L2 (meta/meta-meta) layers are NOT needed here'
        ),
        'notes': (
            'We feed Det\'s high-scoring ruleset as the LUT seed, then '
            'run a small GA to smooth the edges. One level of evolution; '
            'no meta-meta breeding for Isolation.'
        ),
    },
    {
        'order': 3,
        'app_label': 'automaton',
        'entrypoint': 'automaton.runner.run_ruleset',
        'produces': 'Frame sequence + class-4 heuristic verdict',
        'fields_used': (
            'Ruleset: ruleset_hex, colours, neighbourhood\n'
            'Run: grid_w, grid_h, generations\n'
            '— keep: detect_patterns hook; drop: identity-assertion writeback'
        ),
        'notes': (
            'Both Det and Evolution feed candidates here in parallel; '
            'this is the human-in-the-loop verdict stage.'
        ),
    },
]


# Platform-specific stub notes — not code, just seed the status grid
# with what the binding constraint looks like on each target.
HEX_CA_TARGET_STUBS = {
    'cli_oneliner': (
        'Budget ≤80 chars. Probably awk-over-/dev/urandom driving a hex '
        'grid printed with ANSI colour. Neighbourhood=6 means an unrolled '
        'LUT won\'t fit; need an index formula instead.'
    ),
    'c_compact': (
        'Budget ≤1000 chars of C. One file, no headers beyond stdio/stdlib. '
        'Pack the LUT in a static const uint8_t[]; render to stdout with '
        '"\\x1b[48;5;Nm  ".'
    ),
    'attiny13a': (
        '1 KB flash, 64 B RAM. 4^6 = 4096 LUT entries × 2 bits = 1024 B — '
        'won\'t fit; probably infeasible without a symmetry-reduced rule. '
        'First pass: print class-4 output pattern blindly to a ST7735S.'
    ),
    'attiny85': (
        '8 KB flash, 512 B RAM. 1 KB LUT fits; RAM buffer for a small grid '
        '(say 16x16, 4-col packed = 128 B) fits. ST7735S render.'
    ),
    'esp8266': (
        'Plenty of headroom. Target: run live on OLED or ST7735S; pipe '
        'candidate hex strings in over WiFi so the board becomes the '
        'visualiser of the Velour-side Det/Evolution loop.'
    ),
    'esp32': (
        'Same as ESP8266 but with room for multiple rulesets side-by-side '
        'and an onboard scorer (detect class-4 locally, vote).'
    ),
    'esp32_s3': (
        'ESP32-S3 SuperMini: 512 KB SRAM + PSRAM headroom + native USB-OTG. '
        'Run a small population on-device, score locally, stream winners '
        'over USB CDC. The platformio.ini in artifacts/hex_ca_class4/'
        'esp_st7735s/ already has an esp32s3 env wired up.'
    ),
    'pi4': (
        'Full Python reimplementation of all three stages in a single '
        'file — the "reference isolation" against which tinier targets '
        'are validated.'
    ),
}


class Command(BaseCommand):
    help = 'Seed Isolation with the hex-CA class-4 pipeline.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
            help='Delete the existing hex-CA pipeline and recreate it.')

    def handle(self, *args, **opts):
        if opts['reset']:
            deleted = Pipeline.objects.filter(slug=HEX_CA_SLUG).delete()
            if deleted[0]:
                self.stdout.write(self.style.WARNING(
                    f'Deleted existing pipeline "{HEX_CA_SLUG}".'))

        pipeline, created = Pipeline.objects.get_or_create(
            slug=HEX_CA_PIPELINE['slug'],
            defaults={k: v for k, v in HEX_CA_PIPELINE.items() if k != 'slug'},
        )
        if not created:
            for k, v in HEX_CA_PIPELINE.items():
                if k != 'slug':
                    setattr(pipeline, k, v)
            pipeline.save()
            self.stdout.write(f'Updated pipeline "{pipeline.name}".')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Created pipeline "{pipeline.name}".'))

        for s in HEX_CA_STAGES:
            stage, s_created = Stage.objects.update_or_create(
                pipeline=pipeline, order=s['order'],
                defaults={k: v for k, v in s.items() if k != 'order'},
            )
            verb = 'Created' if s_created else 'Updated'
            self.stdout.write(f'  {verb} stage #{stage.order}: '
                              f'{stage.app_label}.{stage.entrypoint}')

        pipeline.ensure_all_targets()
        for key, stub in HEX_CA_TARGET_STUBS.items():
            t = IsolationTarget.objects.get(pipeline=pipeline, target=key)
            if not t.notes.strip():
                t.notes = stub
                t.save(update_fields=['notes'])

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {pipeline.stages.count()} stages and '
            f'{pipeline.targets.count()} target stubs for '
            f'"{pipeline.name}".'))

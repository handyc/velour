"""Seed the Isolation `oneclick-hex-class4` pipeline.

This is the *hunt* pipeline (sibling to the existing hex-ca-class4
which is the *simulator* pipeline). Stages:

  det.pipeline.run_oneclick_pipeline
    → random packed seed → mutate to population → GA →
      tournament → promote top winners as Automaton rulesets

The compact artifacts collapse the whole chain into a single
self-replicating binary (hunter.c + pi4.py) so the pipeline can run
far from Django.

Run:
    venv/bin/python manage.py seed_oneclick_pipeline
Reset:
    venv/bin/python manage.py seed_oneclick_pipeline --reset
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from isolation.models import IsolationTarget, Pipeline, Stage


SLUG = 'oneclick-hex-class4'

PIPELINE = {
    'slug': SLUG,
    'name': 'Hex-CA class-4 one-click hunt',
    'apps_used': 'det, automaton',
    'origin_target': 'pi4',
    'description':
        'Single-button Class-4 discovery. Start from a random packed '
        '4 KB genome (or a previous winner), mutate to a population, '
        'run a small GA, tournament across multiple seed grids, and '
        'emit the winning rulesets. In Velour this lives behind '
        '/det/oneclick/ and promotes to Automaton. The standalone '
        'artifacts fold the whole pipeline into a self-replicating '
        'binary: the last 4096 bytes of the executable ARE the seed '
        'genome, and each output winner is another copy of the same '
        'engine with a fresh genome glued to its tail.',
    'notes':
        'Compact C target is a self-replicating design: engine bytes '
        'at the head, seed genome at the tail, winners written as '
        '[engine_bytes ++ winner_genome] so each output is runnable. '
        'Current size on glibc x86-64: ~18.5 KB (14.5 KB engine + 4 KB '
        'seed). Static musl or -nostdlib builds should drop this to '
        '~6-8 KB total. ATtiny targets infeasible (the 4 KB genome '
        'alone is ~2× the ATtiny85\'s SRAM budget).',
}

STAGES = [
    {
        'order': 1, 'app_label': 'det', 'entrypoint': 'pipeline.run_oneclick_pipeline',
        'produces': 'PipelineResult (promoted RuleSet ids, tournament ranking)',
        'fields_used': 'n_colors\npopulation_size\ngenerations\ntournament_seeds\nfinal_winners',
        'notes': 'Orchestrator. Drives stages 2-5. Exposed on the Det '
                 'home page as the green "Hunt Class-4" button.',
    },
    {
        'order': 2, 'app_label': 'automaton', 'entrypoint': 'packed.PackedRuleset',
        'produces': '4096-byte packed ruleset (K=4, 16384 situations, 2 bits/output)',
        'fields_used': 'n_colors\nbits_per_cell\nn_situations\ndata (bytearray 4096)',
        'notes': 'Genome representation. mutate/crossover/hamming are '
                 'methods on the class. Serialises as hex.',
    },
    {
        'order': 3, 'app_label': 'automaton', 'entrypoint': 'detector.step_packed',
        'produces': 'Next-tick grid (list of lists of ints)',
        'fields_used': '',
        'notes': 'Fitness-eval inner loop. One memory fetch + bit '
                 'extract per cell per tick. ~12.9× faster than '
                 'step_exact on a typical workload.',
    },
    {
        'order': 4, 'app_label': 'det', 'entrypoint': 'pipeline._score_packed',
        'produces': 'float score (class-4 proxy) + analysis dict',
        'fields_used': 'activity_tail\nblock_entropy\ncolor_diversity\nperiod',
        'notes': 'Borrows det.search._score so the Python pipeline '
                 'scores identically to the legacy search. Standalone '
                 'artifacts reimplement the same weights inline.',
    },
    {
        'order': 5, 'app_label': 'det', 'entrypoint': 'pipeline._promote_to_automaton',
        'produces': 'automaton.RuleSet + ExactRule + Simulation rows',
        'fields_used': 'RuleSet.name\nRuleSet.palette\nRuleSet.source_metadata\nExactRule.n0_color..n5_color\nSimulation.grid_state',
        'notes': 'Final step in the Django version — saves top winners '
                 'to /automaton/. Compact artifacts print hex instead.',
    },
]


# (target, status, artifact_path, size_bytes, notes)
TARGETS = [
    ('cli_oneliner', 'infeasible', '', None,
     'A 4096-byte packed genome alone exceeds an 80-char oneliner by '
     '~50×. The hunt requires per-tick simulation of a hex grid, '
     'which can\'t compress into a single shell pipe. Conceptually '
     'impossible at this size.'),
    ('c_compact', 'working',
     'isolation/artifacts/oneclick_class4/hunter.c', 14464,
     'Self-replicating design. Engine = 14.5 KB after -Os -s on '
     'glibc x86-64. Plus 4 KB of seed genome = 18.5 KB total binary. '
     'Build with ./build.sh. A musl-static or -nostdlib build would '
     'fit under 16 KB cleanly. See build.sh for bootstrap notes.'),
    ('attiny13a', 'infeasible', '', None,
     'ATtiny13a has 1 KB flash and 64 B RAM. The 4 KB genome '
     'cannot fit on the device, let alone a population of them. '
     'Hard physical limit.'),
    ('attiny85', 'infeasible', '', None,
     'ATtiny85 has 8 KB flash and 512 B RAM. Could store one 4 KB '
     'genome in flash, but no way to evolve it in 512 B of SRAM. '
     'Infeasible without off-chip memory.'),
    ('esp8266', 'attempted',
     'isolation/artifacts/oneclick_class4/hunter.c', None,
     'ESP8266 has ~80 KB free SRAM. One 4 KB genome + a small '
     'population (say 8 agents) would just fit. The hunter.c source '
     'should port with tiny changes (replace stat()/stdio with SPIFFS '
     'and Serial). Not attempted yet.'),
    ('esp32', 'attempted',
     'isolation/artifacts/oneclick_class4/hunter.c', None,
     'ESP32 has ~320 KB SRAM — room for a 30-agent population of '
     '4 KB genomes with headroom. Good fit for the hunt loop; the '
     'self-replication part would need either SD-card writes or be '
     'dropped in favour of serial-out hex. Not attempted yet.'),
    ('pi4', 'working',
     'isolation/artifacts/oneclick_class4/pi4.py', None,
     'Standalone Python — no Django. Default params (25 × 12 × '
     '14×14 × 25) finish in a few seconds on a Pi 4. The canonical '
     'reference for the algorithm; the C version is a direct port.'),
]


class Command(BaseCommand):
    help = 'Seed the Isolation oneclick-hex-class4 pipeline.'

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

        # Update every target row with what we know
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

        # Auto-measure any artefact we have on disk
        for t in pipeline.targets.all():
            if t.artifact_path and t.size_bytes is None:
                p = Path(t.artifact_path).resolve()
                if p.exists() and p.is_file():
                    t.size_bytes = p.stat().st_size
                    t.save(update_fields=['size_bytes'])

        self.stdout.write(self.style.SUCCESS(
            f'Done. {pipeline.targets.count()} targets on '
            f'{pipeline.slug}.'))

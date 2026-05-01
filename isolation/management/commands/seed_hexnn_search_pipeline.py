"""Seed the Isolation `hexnn-class4-search` pipeline.

This is the *HexNN hunt* pipeline — sibling to `oneclick-hex-class4`,
but for the nearest-neighbour CA format, not the K=4 positional one.

Stages mirror the in-browser bench at /hexnn/:

  1. hexnn.engine.random_genome   — make a {2**n_log2}-prototype rule
  2. hexnn.engine.build_bins      — group prototypes by self-colour
  3. hexnn.engine.step            — nearest-prototype hex stepper
  4. (browser GA in templates/hexnn/index.html: score / mutate /
     crossover / run_ga)         — Hunt + Refine GA on quantize-K=4
                                   change-rate fitness
  5. hexnn.genome.encode/decode   — wire format (HXNN magic + body)

The compact artifacts collapse the chain for places far from Django:
  - `pi4.py`            — numpy reference; runs anywhere with python3
  - `esp32_s3/`         — PlatformIO project; flashes onto the
                          SuperMini and persists the elite to LittleFS

Run:
    venv/bin/python manage.py seed_hexnn_search_pipeline
Reset:
    venv/bin/python manage.py seed_hexnn_search_pipeline --reset
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from isolation.models import IsolationTarget, Pipeline, Stage


SLUG = 'hexnn-class4-search'

PIPELINE = {
    'slug': SLUG,
    'name': 'HexNN nearest-neighbour CA — class-4 search',
    'apps_used': 'hexnn',
    'origin_target': 'pi4',
    'description':
        'Port of the /hexnn/ browser bench: random {2**n_log2}-'
        'prototype nearest-neighbour CA genome, Hunt + Refine GA on '
        'a small population, edge-of-chaos parabola fitness on the '
        'K=4-quantized change rate. Same wire format as hexnn.genome '
        '(HXNN magic + K + n_log2 + body). The Pi reference is the '
        'canonical algorithm; the S3 sketch is a 1:1 transliteration '
        'with on-chip mulberry32 + LittleFS persistence.',
    'notes':
        'Sibling to oneclick-hex-class4 (HXC4 positional format). '
        'The two genome formats never share code: HXC4 is a single '
        '4 KB packed lookup; HXNN is a list of prototypes matched by '
        'nearest-neighbour, where the entry count is dialable. The '
        'browser bench defaults to N_LOG2=14 (16,384 prototypes); the '
        'S3 default is 11 (2,048) so a population of 8 fits in SRAM '
        'without PSRAM. Same scoring / mutation axes as the JS GA.',
}

STAGES = [
    {
        'order': 1, 'app_label': 'hexnn', 'entrypoint': 'engine.random_genome',
        'produces': 'Genome (K, n_log2, palette, keys, outputs)',
        'fields_used': 'K\nn_log2\npalette (K bytes)\nkeys (N tuples)\noutputs (N bytes)',
        'notes': 'mulberry32-seeded random fill, byte-identical to the '
                 'browser when given the same seed.',
    },
    {
        'order': 2, 'app_label': 'hexnn', 'entrypoint': 'engine.build_bins',
        'produces': 'List of (neighbours[M,6], outputs[M]) per self-colour',
        'fields_used': 'Genome.keys[:,0] (self-colour buckets)',
        'notes': 'Constant-time per cell amortised: bins shrink the '
                 'lookup from N to ~N/K. Allocation is shared-arena '
                 'on-device so the cost is N×7 bytes total instead of '
                 'K × worst-case N.',
    },
    {
        'order': 3, 'app_label': 'hexnn', 'entrypoint': 'engine.step',
        'produces': 'Next-tick (H, W) grid',
        'fields_used': '',
        'notes': 'Flat-top offset-column hex math, matches s3lab and '
                 'automaton.detector. Edge cells treat OOB neighbours '
                 'as colour 0 (engine convention).',
    },
    {
        'order': 4, 'app_label': 'hexnn',
        'entrypoint': 'templates/hexnn/index.html (startHunt + score + mutate)',
        'produces': 'Best-fit Genome over GENS generations',
        'fields_used': 'mutation_rate\npop_size\ngens\nhorizon\nburn_in',
        'notes': 'In-browser GA. Score = 4·r·(1-r) where r is the '
                 'mean K=4-quantized change rate after burn-in. '
                 'Mutation = output reassign + key drift ±1 (clamped). '
                 'Crossover = single-cut at a random prototype index. '
                 'Hunt = half mutated + half random; Refine = all '
                 'mutated. Pi-side reference reimplements this in '
                 'numpy; S3 reimplements in C++.',
    },
    {
        'order': 5, 'app_label': 'hexnn', 'entrypoint': 'genome.encode',
        'produces': 'HXNN bytes — 8-byte header + palette + N×8 entries',
        'fields_used': 'Genome.k\nGenome.n_log2\nGenome.palette\nGenome.keys\nGenome.outputs',
        'notes': 'Wire format. Browser export at /hexnn/ writes the '
                 'JSON variant; engine.encode/decode handles the '
                 'binary form. /elite.bin on the device uses a '
                 'simplified shape (no palette).',
    },
]


# (target, status, artifact_path, size_bytes, notes)
TARGETS = [
    ('cli_oneliner', 'infeasible', '', None,
     'A single random {2**11}-prototype genome is ~16 KB. Even the '
     'smallest reasonable hunt needs a population of those plus a '
     'grid stepper — three orders of magnitude past 80 chars. '
     'Conceptually impossible at this scale.'),
    ('c_compact', 'attempted', '', None,
     'Could in principle fit a *single fixed* HexNN genome + step + '
     'render under 1000 chars by dropping the GA, the bins, the '
     'persistence, and accepting K=2 with N_LOG2=8. Not built — the '
     'point of the format is the search, and the search needs '
     'memory the c_compact tier doesn\'t have.'),
    ('attiny13a', 'infeasible', '', None,
     'ATtiny13a has 1 KB flash and 64 B RAM. A single genome at '
     'N_LOG2=11 is 16 KB — the genome alone is 16× the chip\'s '
     'flash, never mind RAM. Hard physical limit.'),
    ('attiny85', 'infeasible', '', None,
     'ATtiny85 has 8 KB flash and 512 B SRAM. Could *fit* a tiny '
     '(N_LOG2=8, K=2) genome in flash but cannot run the bin lookup '
     'with 512 B of RAM, let alone the GA. Infeasible without off-'
     'chip memory.'),
    ('esp8266', 'attempted', '', None,
     'ESP8266 has ~80 KB free SRAM. A single genome at N_LOG2=11 '
     '(16 KB) plus bins (~16 KB) and a small population of 4 '
     'fits in BSS with ~16 KB headroom. The S3 sketch should port '
     'with minor changes (replace LittleFS with SPIFFS, adjust '
     'partition table). Not attempted yet.'),
    ('esp32', 'attempted', '', None,
     'ESP32 (non-S3) has ~320 KB SRAM. Same code as the S3 builds; '
     'the only difference is flash partitioning and the absence of '
     'native USB-CDC. Not attempted yet — S3 is the priority target.'),
    ('esp32_s3', 'working',
     'isolation/artifacts/hexnn_search/esp32_s3/', None,
     'ESP32-S3 SuperMini: full Hunt + Refine GA on-chip, persists '
     'elite to LittleFS, prints hexnn-genome-v1 JSON to USB CDC. '
     'Default config (K=4, N_LOG2=11, POP=8, GENS=30): ~305 KB '
     'static RAM in BSS, leaves ~200 KB for the IDF runtime + heap. '
     'Override K, N_LOG2, POP_SIZE etc. via -D flags in '
     'platformio.ini if you have PSRAM. Wire format byte-identical '
     'to the browser export, so a /elite.bin pulled off the device '
     'with mklittlefs decodes back into pi4.py --input.'),
    ('pi4', 'working',
     'isolation/artifacts/hexnn_search/pi4.py', None,
     'Standalone Python — no Django. Default params (K=4, N_LOG2=14, '
     '16×16 grid, pop 16, gens 60) finishes in a couple minutes on a '
     'Pi 4. The canonical reference for the algorithm; the C++ '
     'version is a direct port. Run with --hunt then --refine to '
     'replicate the browser "Auto" button.\n\n'
     'For HPC scaling, see isolation/artifacts/hexnn_search/hpc/. '
     'Multi-CPU build (cpu.py + cpu.sbatch) ships through Conduit '
     '— `manage.py hexnn_hpc_submit --variant cpu` materialises a '
     'JobHandoff for ALICE. GPU and GPU+CPU hybrid variants are '
     'planned in the same directory.'),
]


class Command(BaseCommand):
    help = 'Seed the Isolation hexnn-class4-search pipeline.'

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
            IsolationTarget.objects.update_or_create(
                pipeline=pipeline, target=target_key,
                defaults={
                    'status':        status,
                    'artifact_path': path,
                    'size_bytes':    size,
                    'notes':         notes,
                },
            )

        # Auto-measure any artefact we have on disk and don't have a
        # baked-in size for.
        for t in pipeline.targets.all():
            if not t.artifact_path or t.size_bytes is not None:
                continue
            p = Path(t.artifact_path).resolve()
            if p.is_file():
                t.size_bytes = p.stat().st_size
                t.save(update_fields=['size_bytes'])
            elif p.is_dir():
                # Sum over the source files we expect to compile.
                total = 0
                for child in p.rglob('*'):
                    if child.is_file() and child.suffix in (
                            '.cpp', '.c', '.h', '.hpp', '.ini'):
                        total += child.stat().st_size
                if total:
                    t.size_bytes = total
                    t.save(update_fields=['size_bytes'])

        self.stdout.write(self.style.SUCCESS(
            f'Done. {pipeline.targets.count()} targets on '
            f'{pipeline.slug}.'))

"""Analyse a pulled-back metapact-ga ALICE bundle.

Usage:
    manage.py alice_analyze_metapact <bundle-slug>

Reads conduit/alice/bundles/<slug>/outputs/*.json and prints a summary.
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from conduit.alice import metapact_ga as mpga


class Command(BaseCommand):
    help = 'Summarise a metapact-ga ALICE bundle that has been pulled back.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--json', action='store_true',
            help='Emit the summary as JSON instead of a text table.')

    def handle(self, *args, **opts):
        slug = opts['slug']
        bundle = (Path(settings.BASE_DIR) / 'conduit' / 'alice'
                    / 'bundles' / slug)
        if not bundle.exists():
            raise CommandError(f'no such bundle: {bundle}')

        summary = mpga.analyse(bundle)
        if opts['json']:
            self.stdout.write(json.dumps(summary, indent=2))
            return

        s = summary
        self.stdout.write(f'Bundle: {s["bundle"]}   status: {s["status"]}')
        if s['status'] == 'no-outputs':
            self.stdout.write(self.style.WARNING(s['hint']))
            return
        self.stdout.write(
            f'  tasks: {s["n_tasks"]}/{s["n_expected"]}'
            f'{"  missing: " + ", ".join(s["missing"]) if s["missing"] else ""}')
        f = s['fitness']
        self.stdout.write(
            f'  fitness:  min={f["min"]:.4f}  median={f["median"]:.4f}  '
            f'mean={f["mean"]:.4f}  max={f["max"]:.4f}')
        e = s['elapsed_seconds']
        self.stdout.write(
            f'  elapsed:  min={e["min"]:.0f}s  median={e["median"]:.0f}s  '
            f'max={e["max"]:.0f}s  total={e["total"]:.0f}s')
        b = s['best']
        self.stdout.write('')
        self.stdout.write('Best replicate:')
        self.stdout.write(f'  task_id:           {b["task_id"]}')
        self.stdout.write(f'  seed_in:           0x{b["seed_in"]:08X}')
        self.stdout.write(f'  best_fitness:      {b["best_fitness"]:.4f}')
        self.stdout.write(f'  chain_quality:     {b["best_chain_quality"]:.4f}')
        self.stdout.write(f'  leaf_fitness:      {b["best_leaf_fitness"]:.4f}')
        self.stdout.write(f'  depth_class4:      {b["depth_class4"]}/{len(b["chain_classes"])}')
        self.stdout.write(f'  chain_classes:     {"".join(str(c) for c in b["chain_classes"])}')

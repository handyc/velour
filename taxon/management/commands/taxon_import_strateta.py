"""Import a strateta-population-v1[.gz] file into the Taxon library.

Each library entry becomes a Rule (kind=hex_nn, K=256). After import
the command runs HexNN simulation + metrics + the Wolfram classifier
on every new rule so the class distribution lands in the Classification
table (visible in /taxon/).

Examples:
  manage.py taxon_import_strateta path/to/strateta-population-K256-….json.gz
  manage.py taxon_import_strateta file.json --no-classify
  manage.py taxon_import_strateta file.json --grid 16 --horizon 60
"""
from __future__ import annotations

import gzip
import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from taxon import importers
from taxon.classifier import classify
from taxon.hexnn import HexNNRuleset, langton_lambda_hexnn, simulate, unpack_hexnn
from taxon.metrics import REGISTRY
from taxon.models import Classification, MetricRun


class Command(BaseCommand):
    help = 'Import a strateta-population-v1 JSON / .json.gz into the Taxon library.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=str,
                            help='Path to strateta-population-v1 JSON or .json.gz')
        parser.add_argument('--no-classify', action='store_true',
                            help='Skip metrics + classifier pass after import.')
        parser.add_argument('--grid', type=int, default=12,
                            help='Grid edge length for simulation (default 12).')
        parser.add_argument('--horizon', type=int, default=40,
                            help='Tick count for simulation (default 40).')
        parser.add_argument('--seed', type=int, default=42,
                            help='Seed for the random initial grid (default 42).')

    def handle(self, *args, **opts):
        p = Path(opts['path'])
        if not p.is_file():
            raise CommandError(f'no such file: {p}')

        raw = p.read_bytes()
        if p.suffix == '.gz' or (len(raw) >= 2 and raw[:2] == b'\x1f\x8b'):
            raw = gzip.decompress(raw)
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception as e:
            raise CommandError(f'failed to parse JSON: {e}')

        self.stdout.write(f'Loaded {p.name} · format={payload.get("format")!r} '
                          f'K={payload.get("K")} entries={len(payload.get("library", []))}')

        try:
            rules = importers.import_strateta_population(
                payload,
                source='strateta',
                source_ref=f'file={p.name}',
            )
        except Exception as e:
            raise CommandError(f'import failed: {e}')

        self.stdout.write(self.style.SUCCESS(
            f'Imported {len(rules)} rule(s) as kind=hex_nn (K={payload["K"]}).'
        ))

        if opts['no_classify']:
            return

        self.stdout.write(
            f'Classifying {len(rules)} rule(s) at {opts["grid"]}×{opts["grid"]} '
            f'× {opts["horizon"]} ticks…'
        )

        cls_counts: Counter[int] = Counter()
        for i, rule in enumerate(rules):
            K, keys, outs = unpack_hexnn(bytes(rule.genome))
            ruleset = HexNNRuleset(K, keys, outs)
            traj, hashes = simulate(ruleset, opts['grid'], opts['grid'],
                                     opts['horizon'], opts['seed'])
            mvals: dict[str, float] = {}
            for name, fn in REGISTRY.items():
                if name == 'langton_lambda':
                    val, extra = langton_lambda_hexnn(ruleset)
                else:
                    val, extra = fn(traj, hashes, ruleset)
                MetricRun.objects.create(
                    rule=rule, metric=name, value=val,
                    grid_w=opts['grid'], grid_h=opts['grid'],
                    horizon=opts['horizon'], seed=opts['seed'],
                    extra_json=extra,
                )
                mvals[name] = val
            cls, conf, basis = classify(mvals, horizon=opts['horizon'], n_colors=K)
            Classification.objects.create(
                rule=rule, wolfram_class=cls, confidence=conf,
                basis_json=basis,
            )
            cls_counts[cls] += 1
            if (i + 1) % 32 == 0 or i + 1 == len(rules):
                self.stdout.write(f'  · {i + 1}/{len(rules)} done')

        self.stdout.write(self.style.SUCCESS('\nClass distribution:'))
        for cls in sorted(cls_counts):
            self.stdout.write(f'  class {cls}: {cls_counts[cls]}')

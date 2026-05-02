"""Bulk-import rules from sibling apps into the Taxon library.

Examples:
  manage.py taxon_import --automaton-all
  manage.py taxon_import --hexhunt-all
  manage.py taxon_import --hxc4 path/to/winner.bin --name "Stratum #1 elite"
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from taxon import importers
from taxon.classifier import classify
from taxon.engine import simulate
from taxon.metrics import run_all
from taxon.models import Classification, MetricRun, Rule
from automaton.packed import PackedRuleset


class Command(BaseCommand):
    help = 'Import CA rules into the Taxon library from sibling apps.'

    def add_arguments(self, parser):
        parser.add_argument('--automaton-all', action='store_true',
                            help='Import every K=4 RuleSet from automaton.')
        parser.add_argument('--hexhunt-all', action='store_true',
                            help='Import every HuntRule from helix.')
        parser.add_argument('--hxc4', type=str, default=None,
                            help='Path to a 4,104-byte HXC4 / genome.bin file.')
        parser.add_argument('--name', type=str, default='',
                            help='Optional display name (with --hxc4).')
        parser.add_argument('--source', type=str, default='manual',
                            help='Source label (with --hxc4).')
        parser.add_argument('--no-classify', action='store_true',
                            help='Skip metric+classify pass after import.')
        parser.add_argument('--horizon', type=int, default=120)
        parser.add_argument('--grid', type=int, default=24)
        parser.add_argument('--seed', type=int, default=42)

    def handle(self, *args, **opts):
        imported: list[Rule] = []

        if opts['automaton_all']:
            from automaton.models import RuleSet
            for rs in RuleSet.objects.filter(n_colors=4):
                rule = importers.import_automaton_ruleset(rs)
                if rule:
                    imported.append(rule)
                    self.stdout.write(f'  ← automaton  {rs.slug}')

        if opts['hexhunt_all']:
            try:
                from helix.models import HuntRule
            except Exception as e:
                raise CommandError(f'helix not available: {e}')
            for hr in HuntRule.objects.all():
                rule = importers.import_huntrule(hr)
                imported.append(rule)
                self.stdout.write(f'  ← helix      {hr.slug}')

        if opts['hxc4']:
            p = Path(opts['hxc4'])
            if not p.is_file():
                raise CommandError(f'no such file: {p}')
            blob = p.read_bytes()
            rule = importers.import_hxc4_blob(
                blob, name=opts['name'] or p.stem,
                source=opts['source'], source_ref=str(p),
            )
            imported.append(rule)
            self.stdout.write(f'  ← {opts["source"]:10s} {p.name}')

        if not imported:
            self.stdout.write(self.style.WARNING(
                'Nothing imported. Pass --automaton-all, --hexhunt-all, '
                'or --hxc4 PATH.'
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Imported {len(imported)} rule(s).'
        ))

        if opts['no_classify']:
            return

        self.stdout.write('Running metrics + classifier on new imports …')
        for rule in imported:
            packed = PackedRuleset(n_colors=4, data=bytes(rule.genome))
            traj, hashes = simulate(
                packed, opts['grid'], opts['grid'],
                opts['horizon'], opts['seed'],
            )
            results = run_all(traj, hashes, packed)
            mvals = {}
            for name, (val, extra) in results.items():
                MetricRun.objects.create(
                    rule=rule, metric=name, value=val,
                    grid_w=opts['grid'], grid_h=opts['grid'],
                    horizon=opts['horizon'], seed=opts['seed'],
                    extra_json=extra,
                )
                mvals[name] = val
            cls, conf, basis = classify(mvals, horizon=opts['horizon'])
            Classification.objects.create(
                rule=rule, wolfram_class=cls, confidence=conf,
                basis_json=basis,
            )
            self.stdout.write(
                f'  ✓ {rule.slug:30s} class {cls} (conf {conf:.2f}, '
                f'λ={mvals.get("langton_lambda", 0):.2f}, '
                f'act={mvals.get("activity_rate", 0):.2f})'
            )

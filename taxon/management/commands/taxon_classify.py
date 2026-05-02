"""Re-run metrics + classifier on existing rules.

Examples:
  manage.py taxon_classify                 # all rules without a classification
  manage.py taxon_classify --all           # every rule (re-classify)
  manage.py taxon_classify --slug foo-bar  # one specific rule
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from automaton.packed import PackedRuleset
from taxon.classifier import classify
from taxon.engine import simulate
from taxon.metrics import run_all
from taxon.models import Classification, MetricRun, Rule


class Command(BaseCommand):
    help = 'Compute metrics and Wolfram class for stored rules.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true')
        parser.add_argument('--slug', type=str, default=None)
        parser.add_argument('--horizon', type=int, default=120)
        parser.add_argument('--grid', type=int, default=24)
        parser.add_argument('--seed', type=int, default=42)

    def handle(self, *args, **opts):
        qs = Rule.objects.all()
        if opts['slug']:
            qs = qs.filter(slug=opts['slug'])
        elif not opts['all']:
            # Default: only rules without any classification yet.
            qs = qs.filter(classifications__isnull=True).distinct()

        n = qs.count()
        if n == 0:
            self.stdout.write(self.style.WARNING(
                'No rules to classify. Pass --all or --slug.'
            ))
            return

        self.stdout.write(f'Classifying {n} rule(s) …')
        for rule in qs:
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
                f'  ✓ {rule.slug:30s} → class {cls} (conf {conf:.2f}, '
                f'λ={mvals.get("langton_lambda", 0):.2f}, '
                f'act={mvals.get("activity_rate", 0):.2f}, '
                f'period={mvals.get("attractor_period", 0):.0f})'
            )

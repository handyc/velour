"""Sweep an evolved rule across a SequenceRecord, persist as RuleFilterScan.

Usage:
    manage.py hexhunt_scan <rule_slug> <record_pk> \\
        --window 256 --stride 128 --score edge \\
        [--start 0 --end 1000000]

The result lives at ``/helix/hexhunt/scans/<slug>/`` and shows a
richness track that lays alongside the record's existing annotation
features.
"""

import math

from django.core.management.base import BaseCommand, CommandError

from helix.hexhunt import engine
from helix.hexhunt.scan import scan_record, estimate_runtime_seconds
from helix.models import HuntRule, RuleFilterScan, SequenceRecord


class Command(BaseCommand):
    help = 'Sweep one HuntRule across a SequenceRecord, store per-window score.'

    def add_arguments(self, parser):
        parser.add_argument('rule_slug')
        parser.add_argument('record_pk', type=int)
        parser.add_argument('--window', type=int, default=256)
        parser.add_argument('--stride', type=int, default=128)
        parser.add_argument('--score', default='edge',
                            help='Scoring function (edge, change, gzip).')
        parser.add_argument('--steps', type=int, default=engine.TOTAL_STEPS)
        parser.add_argument('--start', type=int, default=0)
        parser.add_argument('--end', type=int, default=0,
                            help='0 = full record length.')

    def handle(self, *args, **opts):
        try:
            rule = HuntRule.objects.get(slug=opts['rule_slug'])
        except HuntRule.DoesNotExist:
            raise CommandError(f'no HuntRule with slug={opts["rule_slug"]!r}')
        try:
            record = SequenceRecord.objects.get(pk=opts['record_pk'])
        except SequenceRecord.DoesNotExist:
            raise CommandError(f'no SequenceRecord with pk={opts["record_pk"]}')

        wsize = opts['window']
        stride = opts['stride']
        a = max(0, opts['start'])
        b = opts['end'] if opts['end'] > 0 else record.length_bp
        b = min(b, record.length_bp)
        if b <= a + wsize:
            raise CommandError(f'range [{a}, {b}) too short for window={wsize}')

        n_windows = (b - a - wsize) // stride + 1
        eta = estimate_runtime_seconds(b - a, wsize, stride)
        self.stdout.write(
            f'Scanning {record.title} [{a:,}–{b:,}] '
            f'({n_windows:,} windows, ~{math.ceil(eta)}s) '
            f'with rule {rule.slug} · score={opts["score"]}'
        )

        rule_table = engine.unpack_rule(rule.packed())

        def progress(i, n):
            self.stdout.write(
                f'  {i:>7,}/{n:,}  ({100.0 * i / max(1, n):5.1f}%)'
            )

        result = scan_record(
            record, rule_table,
            window_size=wsize, stride=stride,
            start=a, end=b,
            steps=opts['steps'], scoring_fn=opts['score'],
            on_progress=progress, progress_every=max(100, n_windows // 20),
        )

        scan = RuleFilterScan.objects.create(
            slug=RuleFilterScan.make_slug(),
            rule=rule, record=record,
            window_size=wsize, stride=stride,
            scoring_fn=opts['score'],
            track_json=result.track,
            n_windows=result.n_windows,
            score_min=result.score_min,
            score_max=result.score_max,
            score_mean=result.score_mean,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Scan {scan.slug} done. '
            f'{result.n_windows:,} windows in {result.elapsed_s:.1f}s; '
            f'score min/mean/max = {result.score_min:.4f} / '
            f'{result.score_mean:.4f} / {result.score_max:.4f}.'
        ))

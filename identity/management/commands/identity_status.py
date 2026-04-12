"""A one-shot introspection report on Identity's current state.

Intended for operators running Velour headlessly — e.g. via ssh on
a production host — who want a scannable "what is Identity thinking
right now" dump without having to open a browser.

Prints:
  - The Identity row (name, mood, mood_intensity, hostname)
  - The latest Tick (mood, rule, thought, aspects)
  - Open concerns (with severity, age, reconfirm count)
  - Recent Reflection / Meditation counts and the newest titles
  - Cron dispatcher history for the last few runs
  - The trained Oracle rumination_template lobe's current state
    (labeled vs unlabeled examples, most recent retrain)
  - Five most recent Ticks with abbreviated thoughts

Usage:
    python manage.py identity_status
    python manage.py identity_status --verbose   (include more ticks)
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Print a one-shot introspection report on Identity state.'

    def add_arguments(self, parser):
        parser.add_argument('--verbose', action='store_true',
                            help='Include more ticks and a longer cron history.')

    def handle(self, *args, **opts):
        from identity.models import (
            Identity, Tick, Concern, Reflection, Meditation, CronRun,
        )

        identity = Identity.get_self()
        now = timezone.now()

        # --- Header ----------------------------------------------------
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'=== {identity.name} @ {identity.hostname} — '
            f'{now:%Y-%m-%d %H:%M:%S} ==='))
        self.stdout.write(
            f'  mood:      {identity.mood} ({identity.mood_intensity:.2f})')
        self.stdout.write(
            f'  tagline:   {identity.tagline}')
        self.stdout.write('')

        # --- Latest Tick ----------------------------------------------
        latest = Tick.objects.first()
        if latest:
            self.stdout.write(self.style.SUCCESS('--- latest tick ---'))
            age_sec = int((now - latest.at).total_seconds())
            self.stdout.write(
                f'  at:        {latest.at:%Y-%m-%d %H:%M:%S}  '
                f'({age_sec}s ago, via {latest.triggered_by})')
            self.stdout.write(f'  mood:      {latest.mood} '
                              f'({latest.mood_intensity:.2f})')
            self.stdout.write(f'  rule:      {latest.rule_label}')
            self.stdout.write(f'  aspects:   {latest.aspects}')
            self.stdout.write(f'  thought:   {latest.thought}')
            self.stdout.write('')

        # --- Open concerns --------------------------------------------
        concerns = Concern.objects.filter(closed_at=None).order_by('-severity')
        self.stdout.write(self.style.SUCCESS(
            f'--- open concerns ({concerns.count()}) ---'))
        if concerns:
            for c in concerns:
                age_min = int((now - c.opened_at).total_seconds() / 60)
                self.stdout.write(
                    f'  {c.aspect:25s} severity={c.severity:.2f}  '
                    f'reconfirms={c.reconfirm_count}  age={age_min}m')
                self.stdout.write(f'    {c.name}')
        else:
            self.stdout.write('  (none — Identity is at ease)')
        self.stdout.write('')

        # --- Reflections + Meditations --------------------------------
        self.stdout.write(self.style.SUCCESS('--- reflections ---'))
        ref_count = Reflection.objects.count()
        self.stdout.write(f'  total:     {ref_count}')
        latest_ref = Reflection.objects.first()
        if latest_ref:
            self.stdout.write(
                f'  newest:    [{latest_ref.period}] {latest_ref.title}')
            self.stdout.write(
                f'             ({latest_ref.ticks_referenced} ticks, '
                f'{latest_ref.composed_at:%Y-%m-%d %H:%M})')
        self.stdout.write('')

        self.stdout.write(self.style.SUCCESS('--- meditations ---'))
        med_count = Meditation.objects.count()
        by_depth = {}
        for m in Meditation.objects.all():
            by_depth.setdefault(m.depth, 0)
            by_depth[m.depth] += 1
        self.stdout.write(f'  total:     {med_count}')
        for depth in sorted(by_depth):
            self.stdout.write(f'  level {depth}:   {by_depth[depth]}')
        latest_med = Meditation.objects.first()
        if latest_med:
            self.stdout.write(
                f'  newest:    [L{latest_med.depth} {latest_med.voice}] '
                f'{latest_med.title}')
        self.stdout.write('')

        # --- Cron dispatcher ------------------------------------------
        self.stdout.write(self.style.SUCCESS('--- cron dispatcher ---'))
        n_runs = 10 if opts['verbose'] else 5
        recent_runs = CronRun.objects.all()[:n_runs]
        if recent_runs:
            for r in recent_runs:
                status = self.style.SUCCESS(r.status) if r.status == 'ok' \
                    else self.style.ERROR(r.status)
                self.stdout.write(
                    f'  {r.at:%Y-%m-%d %H:%M:%S}  [{r.kind:18s}] '
                    f'{status}  {r.summary[:60]}')
        else:
            self.stdout.write('  (no runs yet — cron not wired up?)')
        self.stdout.write('')

        # --- Oracle rumination lobe -----------------------------------
        self.stdout.write(self.style.SUCCESS(
            '--- Oracle: rumination_template lobe ---'))
        try:
            from oracle.models import OracleLabel
            total = OracleLabel.objects.filter(
                lobe_name='rumination_template').count()
            good = OracleLabel.objects.filter(
                lobe_name='rumination_template', verdict='good').count()
            bad = OracleLabel.objects.filter(
                lobe_name='rumination_template', verdict='bad').count()
            unlabeled = total - OracleLabel.objects.filter(
                lobe_name='rumination_template'
            ).exclude(verdict='').count()
            self.stdout.write(f'  total predictions:   {total}')
            self.stdout.write(f'  operator-verified:   {good} good / {bad} bad')
            self.stdout.write(f'  unlabeled:           {unlabeled}')
        except Exception as e:
            self.stdout.write(f'  (oracle not reachable: {e})')
        try:
            import os
            from django.conf import settings
            path = os.path.join(
                settings.BASE_DIR, 'oracle', 'models_dir',
                'rumination_template.tree.json',
            )
            if os.path.exists(path):
                import json
                with open(path) as f:
                    lobe = json.load(f)
                self.stdout.write(f'  trained_at:          {lobe.get("trained_at", "?")}')
                self.stdout.write(f'  features:            {lobe.get("features", [])}')
                self.stdout.write(f'  classes:             {lobe.get("classes", [])}')
            else:
                self.stdout.write('  (no trained lobe file yet)')
        except Exception as e:
            self.stdout.write(f'  (lobe file unreadable: {e})')
        self.stdout.write('')

        # --- Self-model accuracy check ---------------------------------
        self.stdout.write(self.style.SUCCESS(
            '--- self-model accuracy check ---'))
        try:
            from identity.self_check import check_self_model, prose_summary
            results = check_self_model()
            self.stdout.write(f'  {prose_summary(results)}')
            inaccurate = [(t, d) for t, d, ok in results if not ok]
            if inaccurate:
                for title, desc in inaccurate:
                    self.stdout.write(self.style.WARNING(
                        f'  ✗ {title}: {desc}'))
            else:
                self.stdout.write(
                    f'  all {len(results)} checks pass')
        except Exception as e:
            self.stdout.write(f'  (check failed: {e})')
        self.stdout.write('')

        # --- Recent ticks tail ----------------------------------------
        tail_n = 10 if opts['verbose'] else 5
        self.stdout.write(self.style.SUCCESS(
            f'--- last {tail_n} ticks ---'))
        for t in Tick.objects.all()[:tail_n]:
            micro = ' [μ]' if t.micro_meditation else ''
            self.stdout.write(
                f'  {t.at:%Y-%m-%d %H:%M:%S}  [{t.mood:14s}] '
                f'v={t.valence:+.1f} a={t.arousal:+.1f}{micro} '
                f'{t.thought[:70]}'
            )
        self.stdout.write('')

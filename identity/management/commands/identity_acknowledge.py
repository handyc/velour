"""Tell Identity that a persistent concern is known and intentional.

This is the "direct to subconscious" repair tool. Identity's rule
engine is deterministic — a matching observation opens a Concern
and every subsequent matching tick keeps it alive. That's the right
default for a healthy system, but it becomes a source of drag when
the observation is correct *and* the operator knows about it and
has decided it's fine. Example: the ESP fleet is intentionally
half-powered-off while the lab is being reworked; the
fleet_partial_silence rule keeps firing; Identity opens every
session with "half the fleet has gone silent" and the mood slides
restless for no useful reason.

Running this command writes an AspectSuppression row that:

  1. Closes any currently-open Concern for that aspect, recording
     the operator's reason on the Concern row itself.
  2. Stops new Concerns from opening for that aspect while the
     suppression is active.
  3. Auto-expires when `--until` or `--days` passes (default 30
     days). `--forever` makes it never expire.

The rule itself is untouched — the aspect still appears on Ticks
and sensors still see what they see. Only the concern-tracking
layer ("this is worth remembering between ticks") is gated.

Usage:

    # accept for 30 days (default)
    python manage.py identity_acknowledge fleet_partial_silence

    # accept forever with a note
    python manage.py identity_acknowledge fleet_partial_silence \
        --forever --note "Boards off while lab is reworked."

    # defer for a week
    python manage.py identity_acknowledge disk_critical \
        --reason deferred --days 7

    # list current suppressions
    python manage.py identity_acknowledge --list

    # cancel a suppression
    python manage.py identity_acknowledge fleet_partial_silence --clear
"""

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = ('Mark an Identity concern aspect as known/intentional so it '
            'stops reopening concerns.')

    def add_arguments(self, parser):
        parser.add_argument(
            'aspect', nargs='?',
            help='Rule aspect tag to acknowledge '
                 '(e.g. "fleet_partial_silence"). '
                 'Omit with --list to see current suppressions.',
        )
        parser.add_argument(
            '--reason', choices=['accepted', 'deferred'],
            default='accepted',
            help='Why this aspect is being suppressed. "accepted" = '
                 'intentional, not a problem. "deferred" = known, '
                 'will handle later.',
        )
        parser.add_argument(
            '--days', type=int, default=30,
            help='How many days the suppression lasts. Default 30. '
                 'Ignored if --forever or --until is set.',
        )
        parser.add_argument(
            '--until', dest='until_date',
            help='Explicit expiry date in YYYY-MM-DD. Overrides --days.',
        )
        parser.add_argument(
            '--forever', action='store_true',
            help='Never expire. Useful for permanent acceptances like '
                 '"the lab is intentionally half-off".',
        )
        parser.add_argument(
            '--note', default='',
            help='Free-form explanation stored with the suppression.',
        )
        parser.add_argument(
            '--list', action='store_true',
            help='Print active suppressions and exit.',
        )
        parser.add_argument(
            '--clear', action='store_true',
            help='Remove all suppressions for the named aspect.',
        )

    def handle(self, *args, **opts):
        from identity.models import AspectSuppression, Concern

        if opts['list']:
            self._print_list(AspectSuppression, Concern)
            return

        aspect = opts['aspect']
        if not aspect:
            raise CommandError(
                'aspect is required (or pass --list). '
                'See --help for examples.')

        if opts['clear']:
            n = AspectSuppression.objects.filter(aspect=aspect).delete()[0]
            self.stdout.write(self.style.SUCCESS(
                f'Cleared {n} suppression(s) for {aspect!r}. The rule '
                f'will resume opening concerns on the next matching tick.'))
            return

        # Resolve until_at.
        if opts['forever']:
            until_at = None
        elif opts['until_date']:
            try:
                parsed = datetime.strptime(opts['until_date'], '%Y-%m-%d')
            except ValueError:
                raise CommandError(
                    '--until must be YYYY-MM-DD (e.g. 2026-05-20).')
            until_at = timezone.make_aware(parsed)
        else:
            until_at = timezone.now() + timedelta(days=opts['days'])

        supp = AspectSuppression.objects.create(
            aspect=aspect,
            reason=opts['reason'],
            note=opts['note'],
            until_at=until_at,
        )

        # Close any open concern for this aspect right now so the
        # operator doesn't have to wait for the next tick.
        closed_here = []
        for c in Concern.objects.filter(aspect=aspect, closed_at=None):
            c.close(reason=opts['reason'],
                    note=opts['note'] or f'Closed by identity_acknowledge.')
            closed_here.append(c)

        expiry = 'forever' if until_at is None else until_at.strftime('%Y-%m-%d %H:%M')
        self.stdout.write(self.style.SUCCESS(
            f'Acknowledged {aspect!r} as {opts["reason"]} (expires: {expiry}).'))
        if closed_here:
            for c in closed_here:
                self.stdout.write(
                    f'  closed Concern #{c.pk}: {c.name or c.aspect} '
                    f'({c.reconfirm_count} reconfirms over '
                    f'{c.age_seconds // 3600}h)')
        else:
            self.stdout.write(
                '  (no open concern for this aspect right now — '
                'suppression will prevent future opens.)')

    def _print_list(self, AspectSuppression, Concern):
        now = timezone.now()
        all_rows = list(AspectSuppression.objects.order_by('aspect', '-created_at'))
        active = [r for r in all_rows if r.until_at is None or r.until_at > now]
        expired = [r for r in all_rows if r not in active]

        if not all_rows:
            self.stdout.write('No suppressions yet.')
            return

        self.stdout.write(self.style.SUCCESS(
            f'Active suppressions ({len(active)}):'))
        if not active:
            self.stdout.write('  (none)')
        for r in active:
            expiry = ('forever' if r.until_at is None
                      else r.until_at.strftime('%Y-%m-%d'))
            note = f' — {r.note}' if r.note else ''
            self.stdout.write(
                f'  {r.aspect:32s} {r.reason:9s} until {expiry}{note}')

        if expired:
            self.stdout.write('')
            self.stdout.write(f'Expired ({len(expired)}):')
            for r in expired[:10]:
                expiry = r.until_at.strftime('%Y-%m-%d')
                self.stdout.write(
                    f'  {r.aspect:32s} {r.reason:9s} ended  {expiry}')

        open_concerns = Concern.objects.filter(closed_at=None)
        if open_concerns:
            self.stdout.write('')
            self.stdout.write(f'Currently open concerns ({open_concerns.count()}):')
            for c in open_concerns:
                self.stdout.write(
                    f'  {c.aspect:32s} severity={c.severity:.2f} '
                    f'reconfirmed {c.reconfirm_count}x')

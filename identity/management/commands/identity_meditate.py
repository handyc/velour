"""Compose an Identity meditation at a given depth level.

Usage:
    python manage.py identity_meditate
        Level 1 contemplative meditation.

    python manage.py identity_meditate --depth 4 --voice wry
        Level 4 (AI-designed self) meditation in the wry voice.

    python manage.py identity_meditate --ladder 1-4 --voice contemplative
        One meditation at each level 1, 2, 3, 4 — each one after the
        first is chained as recursive_of the previous.

    python manage.py identity_meditate --depth 4 --no-codex
        Don't push into the Identity's Mirror Codex manual. The
        Meditation row is still written to the DB.
"""

from django.core.management.base import BaseCommand

from identity.meditation import meditate


class Command(BaseCommand):
    help = 'Compose an Identity meditation at a given depth level.'

    def add_arguments(self, parser):
        parser.add_argument('--depth', type=int, default=1,
                            help='Depth level 1-7 (default 1).')
        parser.add_argument('--voice', default='contemplative',
                            choices=['contemplative', 'wry',
                                     'minimal', 'philosophical'],
                            help='Voice template library (default contemplative).')
        parser.add_argument('--ladder', default='',
                            help='Range of depths to compose in order, '
                                 'e.g. "1-4". Each meditation after the '
                                 'first is chained as recursive_of the '
                                 'previous one.')
        parser.add_argument('--no-codex', action='store_true',
                            help="Skip pushing into the Identity's Mirror Codex manual.")

    def handle(self, *args, **opts):
        push = not opts['no_codex']

        if opts['ladder']:
            try:
                lo, hi = map(int, opts['ladder'].split('-'))
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    f'--ladder expects a range like "1-4", got '
                    f'{opts["ladder"]!r}'))
                return
            prior = None
            for depth in range(lo, hi + 1):
                med = meditate(depth=depth, voice=opts['voice'],
                               push_to_codex=push, recursive_of=prior)
                self._print(med)
                prior = med
            return

        med = meditate(depth=opts['depth'], voice=opts['voice'],
                       push_to_codex=push)
        self._print(med)

    def _print(self, med):
        self.stdout.write(self.style.SUCCESS(
            f'[L{med.depth} {med.voice}] {med.title}'
        ))
        self.stdout.write('')
        self.stdout.write(med.body)
        self.stdout.write('')
        self.stdout.write('---')
        self.stdout.write('')

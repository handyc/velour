"""Run a distillation from the command line and write files to disk.

Usage:
    python manage.py condense tiles --tier js --output /tmp/tiles.html
    python manage.py condense tiles --tier esp --output /tmp/tiles.ino
    python manage.py condense tiles --tier attiny --output /tmp/tiles.c
    python manage.py condense tiles --tier circuit --output /tmp/tiles.txt
    python manage.py condense tiles --tier all    # writes all tiers
    python manage.py condense velour --tier js --output /tmp/velour.html
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run a Condenser distillation and write output to file.'

    def add_arguments(self, parser):
        parser.add_argument('source', choices=['tiles', 'velour'],
                            help='Source to distill.')
        parser.add_argument('--tier', default='js',
                            choices=['js', 'esp', 'attiny', 'circuit', 'all'],
                            help='Target tier (default: js).')
        parser.add_argument('--output', '-o', default='',
                            help='Output file path (default: auto).')

    def handle(self, *args, **options):
        source = options['source']
        tier = options['tier']

        if tier == 'all':
            self._run_all(source)
            return

        output = self._distill(source, tier)
        if output is None:
            return

        path = options['output']
        if not path:
            ext = {'js': 'html', 'esp': 'ino', 'attiny': 'c', 'circuit': 'txt'}[tier]
            path = f'/tmp/{source}_{tier}.{ext}'

        with open(path, 'w') as f:
            f.write(output)
        self.stdout.write(self.style.SUCCESS(
            f'{source} → {tier}: {len(output)} bytes → {path}'))

    def _run_all(self, source):
        tiers = ['js', 'esp', 'attiny', 'circuit']
        exts = {'js': 'html', 'esp': 'ino', 'attiny': 'c', 'circuit': 'txt'}
        prev = None
        for tier in tiers:
            output = self._distill(source, tier, prev_output=prev)
            if output is None:
                break
            path = f'/tmp/{source}_{tier}.{exts[tier]}'
            with open(path, 'w') as f:
                f.write(output)
            self.stdout.write(f'  {tier}: {len(output)} bytes → {path}')
            prev = output
        self.stdout.write(self.style.SUCCESS('Done.'))

    def _distill(self, source, tier, prev_output=None):
        try:
            if source == 'tiles':
                if tier == 'js':
                    from condenser.distill_tiles import distill
                    return distill()
                elif tier == 'esp':
                    from condenser.distill_tiles import distill as d_js
                    from condenser.distill_esp import distill as d_esp
                    js = prev_output or d_js()
                    return d_esp(js)
                elif tier == 'attiny':
                    from condenser.distill_attiny import distill
                    return distill()
                elif tier == 'circuit':
                    from condenser.distill_circuit import distill
                    return distill()
            elif source == 'velour':
                if tier == 'js':
                    from condenser.distill_velour import distill
                    return distill()
                else:
                    self.stderr.write(f'Velour → {tier} not yet implemented.')
                    return None
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Failed: {e}'))
            return None

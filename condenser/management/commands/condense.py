"""Run a Condenser distillation from the command line.

Usage:
    python manage.py condense tiles --tier js
    python manage.py condense tiles --tier all
    python manage.py condense chronos --tier js
    python manage.py condense automaton --tier attiny
    python manage.py condense velour --tier js
"""

from django.core.management.base import BaseCommand


TIER_EXTS = {'js': 'html', 'esp': 'ino', 'attiny': 'c', 'circuit': 'txt'}


class Command(BaseCommand):
    help = 'Condense a Django app through the distillation tiers.'

    def add_arguments(self, parser):
        parser.add_argument('source',
            help='App label to condense (e.g. tiles, chronos, nodes, automaton) or "velour".')
        parser.add_argument('--tier', default='js',
                            choices=['js', 'esp', 'attiny', 'circuit', 'all'])
        parser.add_argument('--output', '-o', default='')

    def handle(self, *args, **options):
        source = options['source']
        tier = options['tier']

        if source == 'velour':
            # Special case: Velour self-distillation
            from condenser.distill_velour import distill
            output = distill()
            path = options['output'] or '/tmp/velour_condensed.html'
            with open(path, 'w') as f:
                f.write(output)
            self.stdout.write(self.style.SUCCESS(
                f'velour → js: {len(output)} bytes → {path}'))
            return

        if tier == 'all':
            self._run_all(source)
        else:
            self._run_one(source, tier, options['output'])

    def _run_one(self, source, tier, output_path):
        from condenser.parser import parse_app, summarize

        ir = parse_app(source)
        if not ir:
            self.stderr.write(self.style.ERROR(f'App "{source}" not found.'))
            return

        gen = self._get_generator(tier)
        if not gen:
            self.stderr.write(self.style.ERROR(f'No generator for tier "{tier}".'))
            return

        output = gen(ir)
        path = output_path or f'/tmp/{source}_{tier}.{TIER_EXTS[tier]}'
        with open(path, 'w') as f:
            f.write(output)

        self.stdout.write(f'{source} → {tier}: {len(output)} bytes → {path}')

    def _run_all(self, source):
        from condenser.parser import parse_app, summarize

        ir = parse_app(source)
        if not ir:
            self.stderr.write(self.style.ERROR(f'App "{source}" not found.'))
            return

        self.stdout.write(summarize(ir))
        self.stdout.write('')

        for tier in ['js', 'esp', 'attiny', 'circuit']:
            gen = self._get_generator(tier)
            if gen:
                try:
                    output = gen(ir)
                    path = f'/tmp/{source}_{tier}.{TIER_EXTS[tier]}'
                    with open(path, 'w') as f:
                        f.write(output)
                    self.stdout.write(f'  {tier}: {len(output)} bytes → {path}')
                except Exception as e:
                    self.stderr.write(f'  {tier}: FAILED — {e}')

        self.stdout.write(self.style.SUCCESS('Done.'))

    def _get_generator(self, tier):
        generators = {}
        try:
            from condenser.gen_js import generate as g_js
            generators['js'] = g_js
        except ImportError:
            pass
        try:
            from condenser.gen_esp import generate as g_esp
            generators['esp'] = g_esp
        except ImportError:
            pass
        try:
            from condenser.gen_attiny import generate as g_attiny
            generators['attiny'] = g_attiny
        except ImportError:
            pass
        try:
            from condenser.gen_circuit import generate as g_circuit
            generators['circuit'] = g_circuit
        except ImportError:
            pass
        return generators.get(tier)

"""Train one or all Oracle lobes from the registry in oracle/lobes.py.

    python manage.py train_lobes                 # train every registered lobe
    python manage.py train_lobes water_plant     # train one by name
    python manage.py train_lobes rumination_template --from-labels
    python manage.py train_lobes water_plant --samples 5000 --max-depth 4

Supersedes the older lobe-specific train_rumination_lobe command. For
each lobe the trainer loads OracleLabel rows with a 'good' verdict (if
--from-labels) and mixes them with fresh synthetic bootstrap examples,
then writes the resulting tree to oracle/models_dir/<name>.tree.json.
"""

import random

from django.core.management.base import BaseCommand, CommandError

from oracle.inference import load_lobe, predict_class, save_lobe
from oracle.lobes import LOBES
from oracle.training import train_lobe


class Command(BaseCommand):
    help = 'Train one or all Oracle lobes.'

    def add_arguments(self, parser):
        parser.add_argument('names', nargs='*',
                            help='Lobe name(s) to train. Empty = all.')
        parser.add_argument('--samples', type=int, default=None,
                            help='Synthetic samples per lobe (overrides '
                                 'the spec default).')
        parser.add_argument('--max-depth', type=int, default=None,
                            help='Override default tree depth.')
        parser.add_argument('--from-labels', action='store_true',
                            help='Also pull OracleLabel rows with verdict=good.')
        parser.add_argument('--labels-only', action='store_true',
                            help='Use ONLY OracleLabel rows (no synthetic).')
        parser.add_argument('--seed', type=int, default=42)

    def handle(self, *args, **opts):
        names = opts['names'] or list(LOBES.keys())
        unknown = [n for n in names if n not in LOBES]
        if unknown:
            raise CommandError(f'Unknown lobe(s): {", ".join(unknown)}. '
                               f'Known: {", ".join(LOBES)}')

        for name in names:
            self._train_one(name, opts)

    def _train_one(self, name, opts):
        spec = LOBES[name]
        rng = random.Random(opts['seed'])
        self.stdout.write(self.style.NOTICE(f'\n=== {name} ==='))
        self.stdout.write(spec.description)

        X, y = [], []
        counts = {c: 0 for c in spec.classes}

        if opts['from_labels'] or opts['labels_only']:
            from oracle.models import OracleLabel
            qs = OracleLabel.objects.filter(
                lobe_name=name, verdict='good').exclude(actual='')
            n_real = 0
            for lb in qs:
                if lb.actual not in spec.classes:
                    continue
                X.append(list(lb.features))
                y.append(spec.classes.index(lb.actual))
                counts[lb.actual] += 1
                n_real += 1
            self.stdout.write(f'  real labels: {n_real}')
            if opts['labels_only'] and n_real == 0:
                self.stderr.write(self.style.ERROR(
                    f'  --labels-only but {name} has no good-verdict rows'))
                return

        if not opts['labels_only']:
            n_synth = opts['samples'] or spec.default_samples
            for _ in range(n_synth):
                features, label = spec.synthesize(rng)
                X.append(features)
                y.append(spec.classes.index(label))
                counts[label] += 1
            self.stdout.write(f'  synthetic samples: {n_synth}')

        self.stdout.write(f'  training set ({len(X)} examples):')
        for cls, c in counts.items():
            pct = c / max(1, len(X))
            self.stdout.write(f'    {cls:20s} {c:5d}  ({pct:.1%})')

        lobe = train_lobe(
            name=name, X=X, y=y,
            feature_names=spec.features,
            class_names=spec.classes,
            max_depth=opts['max_depth'] or spec.default_max_depth,
        )
        lobe['name'] = name
        path = save_lobe(name, lobe)
        self.stdout.write(self.style.SUCCESS(f'  saved: {path}'))

        loaded = load_lobe(name, force_reload=True)
        self.stdout.write('  example predictions:')
        rng2 = random.Random(0)
        for i in range(3):
            features, truth = spec.synthesize(rng2)
            pred = predict_class(loaded, features)
            mark = '✓' if pred == truth else '✗'
            self.stdout.write(f'    {mark} {features} → {pred}  (truth={truth})')

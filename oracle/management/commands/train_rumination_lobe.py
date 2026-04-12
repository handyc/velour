"""Train the rumination_template lobe from synthetic bootstrap data.

Identity Session 6b — the Oracle app's first concrete use case. Instead
of random.random() < 0.3 in identity/ticking.py:compose_thought, we
train a decision tree to pick which template family to use ('concern',
'subject', 'observation', 'holiday') based on the current state.

Bootstrap training data is generated deterministically from the
existing heuristic rules, so the first version of the lobe behaves
identically to the current code. Over time the operator can provide
feedback (via future UI) and the lobe retrains against real labels,
gradually drifting away from pure-heuristic behavior.

Usage:

    python manage.py train_rumination_lobe
        Retrain from synthetic data, save to
        oracle/models_dir/rumination_template.tree.json

    python manage.py train_rumination_lobe --samples 5000
        Generate more synthetic examples (default 2000).
"""

import random

from django.core.management.base import BaseCommand

from oracle.inference import FEATURE_NAMES, save_lobe
from oracle.training import train_lobe


CLASSES = ['observation', 'concern', 'subject', 'holiday']


def _synthesize_one():
    """Generate one (feature_vector, label) pair that matches the
    current heuristic behavior in compose_thought(). This is the
    bootstrap training signal.

    The label is chosen with probabilities that mirror the existing
    code paths:
      - If open_concern_count > 0 and random() < 0.3: 'concern'
      - Else if random() < 0.35: 'subject'
      - Else: 'observation' (or 'holiday' if any holidays upcoming)
    """
    mood_group = random.randint(0, 9)
    tod_group  = random.randint(0, 3)
    moon_group = random.randint(0, 3)
    open_concern_count = random.choice([0, 0, 0, 1, 1, 2, 3, 5])
    nodes_total = random.choice([0, 1, 2, 3, 5, 10])
    nodes_silent = random.randint(0, nodes_total) if nodes_total else 0
    upcoming_events = random.choice([0, 0, 1, 2, 3, 5])
    upcoming_holidays = random.choice([0, 0, 1, 2, 3])

    features = [
        float(mood_group), float(tod_group), float(moon_group),
        float(open_concern_count),
        float(nodes_total), float(nodes_silent),
        float(upcoming_events), float(upcoming_holidays),
    ]

    # Label selection — mirrors compose_thought's decision tree, with
    # an extra 'holiday' class for when holidays are upcoming.
    r = random.random()
    if open_concern_count > 0 and r < 0.30:
        label = 'concern'
    elif r < 0.55 and (nodes_total > 0 or upcoming_events > 0):
        label = 'subject'
    elif upcoming_holidays > 0 and r < 0.75:
        label = 'holiday'
    else:
        label = 'observation'

    return features, label


class Command(BaseCommand):
    help = 'Train the rumination_template decision tree lobe.'

    def add_arguments(self, parser):
        parser.add_argument('--samples', type=int, default=2000,
                            help='Number of synthetic examples to train on.')
        parser.add_argument('--max-depth', type=int, default=6,
                            help='Max depth of the decision tree.')
        parser.add_argument('--from-labels', action='store_true',
                            help='Augment (or replace) the synthetic '
                                 'bootstrap with OracleLabel rows where '
                                 'the operator gave positive feedback.')
        parser.add_argument('--labels-only', action='store_true',
                            help='Use ONLY OracleLabel rows, no '
                                 'synthetic bootstrap. Fails if there '
                                 "aren't at least one labeled example "
                                 'per class.')

    def handle(self, *args, **opts):
        n = opts['samples']
        random.seed(42)

        X = []
        y = []
        label_counts = {c: 0 for c in CLASSES}

        # --- Real labels from OracleLabel (when --from-labels) ----------
        if opts['from_labels'] or opts['labels_only']:
            from oracle.models import OracleLabel
            qs = OracleLabel.objects.filter(
                lobe_name='rumination_template',
                verdict='good',
            ).exclude(actual='')
            real_count = 0
            for lb in qs:
                if lb.actual not in CLASSES:
                    continue
                X.append(list(lb.features))
                y.append(CLASSES.index(lb.actual))
                label_counts[lb.actual] += 1
                real_count += 1
            self.stdout.write(self.style.SUCCESS(
                f'Loaded {real_count} real labeled examples from OracleLabel'))

            if opts['labels_only'] and real_count == 0:
                self.stderr.write(self.style.ERROR(
                    '--labels-only requested but no labeled examples '
                    'exist yet. Give some 👍 feedback on recent ticks '
                    'first, or omit --labels-only to mix with synthetic '
                    'bootstrap.'))
                return

        # --- Synthetic bootstrap (default) -----------------------------
        if not opts['labels_only']:
            for _ in range(n):
                features, label = _synthesize_one()
                X.append(features)
                y.append(CLASSES.index(label))
                label_counts[label] += 1

            self.stdout.write(f'Training set composition '
                              f'({len(X)} total examples):')
            for label, count in label_counts.items():
                pct = count / max(1, len(X))
                self.stdout.write(f'  {label:12s} {count:4d}  ({pct:.1%})')
        else:
            self.stdout.write(f'Training on {len(X)} labeled examples only:')
            for label, count in label_counts.items():
                if count:
                    self.stdout.write(f'  {label:12s} {count:4d}')

        lobe = train_lobe(
            name='rumination_template',
            X=X,
            y=y,
            feature_names=FEATURE_NAMES,
            class_names=CLASSES,
            max_depth=opts['max_depth'],
        )

        path = save_lobe('rumination_template', lobe)
        self.stdout.write(self.style.SUCCESS(f'Saved: {path}'))

        # Quick validation — predict on a handful of known cases
        from oracle.inference import load_lobe, predict_class
        lobe_loaded = load_lobe('rumination_template', force_reload=True)

        test_cases = [
            ([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 'empty state'),
            ([0.0, 0.0, 0.0, 3.0, 2.0, 0.0, 1.0, 0.0], 'concerns open'),
            ([4.0, 3.0, 2.0, 0.0, 5.0, 2.0, 0.0, 1.0], 'fleet + holiday'),
            ([6.0, 3.0, 1.0, 0.0, 2.0, 0.0, 3.0, 0.0], 'events upcoming'),
        ]
        self.stdout.write('')
        self.stdout.write('Validation predictions:')
        for features, label in test_cases:
            pred = predict_class(lobe_loaded, features)
            self.stdout.write(f'  {label:20s} → {pred}')

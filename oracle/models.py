"""Oracle app models.

Phase 2 of the Oracle app: the OracleLabel model. Each row is one
moment where a trained lobe made a prediction, plus (optionally) the
operator's judgment about whether the prediction was right.

Used by the retrain pipeline: labels with `actual` set are treated
as ground-truth training signal the next time the lobe retrains,
gradually drifting the tree away from the synthetic bootstrap and
toward what the operator actually wants.

OracleLabel is intentionally generic — the `lobe_name` field names
which lobe the prediction came from, and the `linked_model` /
`linked_pk` pair lets the row point back to whatever domain object
the decision was about (a Tick, a SensorReading, an Experiment, etc.)
without the oracle app needing to import from any other app.
"""

from django.db import models


class OracleLabel(models.Model):
    """One prediction + (optional) operator judgment for a lobe."""

    VERDICT_CHOICES = [
        ('good', 'Good — predicted the right thing'),
        ('bad',  'Bad — predicted the wrong thing'),
        ('meh',  'Neither clearly right nor wrong'),
    ]
    SOURCE_CHOICES = [
        ('operator', 'Operator feedback'),
        ('auto',     'Auto-derived from downstream outcome'),
        ('synthetic','Synthetic bootstrap data'),
    ]

    lobe_name = models.CharField(max_length=64, db_index=True,
        help_text='Which lobe produced this decision, e.g. '
                  '"rumination_template".')
    happened_at = models.DateTimeField(auto_now_add=True, db_index=True)

    features = models.JSONField(default=list, blank=True,
        help_text='Feature vector the lobe saw at decision time, in '
                  'the order defined by oracle/inference.py '
                  'FEATURE_NAMES.')
    predicted = models.CharField(max_length=64,
        help_text='Class label the lobe picked.')

    actual = models.CharField(max_length=64, blank=True,
        help_text='Ground-truth class the operator says was correct. '
                  'Empty until feedback arrives.')
    verdict = models.CharField(max_length=8, choices=VERDICT_CHOICES,
        blank=True,
        help_text='Shorthand judgment — the operator may not know '
                  'which class was correct but can still flag good/bad.')
    actual_source = models.CharField(max_length=16, choices=SOURCE_CHOICES,
        default='operator')

    linked_model = models.CharField(max_length=64, blank=True,
        help_text='App-label.Model string, e.g. "identity.Tick", if '
                  'this decision was about a specific domain object.')
    linked_pk = models.IntegerField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-happened_at']
        indexes = [
            models.Index(fields=['lobe_name', '-happened_at']),
            models.Index(fields=['lobe_name', 'verdict']),
        ]

    def __str__(self):
        verdict = self.verdict or 'unlabeled'
        return f'[{self.lobe_name}] {self.predicted} ({verdict})'

"""Run a mental health diagnostic on Identity's recent mood history.

Usage:
  python manage.py identity_mental_health              # 24-hour diagnosis
  python manage.py identity_mental_health --hours 168  # 7-day diagnosis
  python manage.py identity_mental_health --save       # persist to database
"""

from django.core.management.base import BaseCommand

from identity.mental_health import (
    compose_health_reflection, diagnose, find_exceptions,
)


class Command(BaseCommand):
    help = "Diagnose Identity's mental health and recommend interventions"

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24,
                            help='Hours of history to analyse (default 24)')
        parser.add_argument('--save', action='store_true',
                            help='Persist diagnosis to database')

    def handle(self, **options):
        hours = options['hours']
        diag = diagnose(hours)

        self.stdout.write(f'\n=== Mental Health Diagnosis ({hours}h) ===\n')
        self.stdout.write(f'Ticks analysed:    {diag.get("tick_count", 0)}')

        if diag.get('tick_count', 0) == 0:
            self.stdout.write(diag['diagnosis'])
            return

        self.stdout.write(f'Average valence:   {diag["avg_valence"]:+.3f}')
        self.stdout.write(f'Average arousal:   {diag["avg_arousal"]:+.3f}')
        self.stdout.write(f'Negative ratio:    {diag["negative_ratio"]:.0%}')
        self.stdout.write(f'Dominant mood:     {diag["dominant_mood"]}')
        self.stdout.write(f'Negative streak:   {diag["negative_streak"]}')
        self.stdout.write(f'Open concerns:     {diag["concern_count"]}')

        if diag.get('mood_distribution'):
            self.stdout.write('\nMood distribution:')
            for mood, count in sorted(diag['mood_distribution'].items(),
                                      key=lambda x: -x[1]):
                bar = '█' * min(40, count)
                self.stdout.write(f'  {mood:16s} {count:4d} {bar}')

        self.stdout.write(f'\nDiagnosis: {diag["diagnosis"]}')

        if diag.get('recommendations'):
            self.stdout.write(f'\nRecommendations:')
            for r in diag['recommendations']:
                self.stdout.write(f'  • {r}')

        # Exception finding for top concerns
        if diag.get('top_concerns'):
            self.stdout.write('\nException finding for top concerns:')
            for concern in diag['top_concerns'][:3]:
                exceptions = find_exceptions(concern['aspect'])
                if exceptions:
                    self.stdout.write(
                        f'  {concern["aspect"]}: absent during '
                        f'{len(exceptions)} recent positive periods')
                    for ex in exceptions[:2]:
                        self.stdout.write(
                            f'    → {ex["at"]:%b %d %H:%M} '
                            f'({ex["mood"]}, v={ex["valence"]:+.2f})')

        # Compose and show reflection
        reflection = compose_health_reflection(diag)
        self.stdout.write(f'\n--- Reflection ---\n{reflection}\n')

        # Compute health score
        score = _compute_score(diag)
        self.stdout.write(f'Health score: {score:.2f}/1.00')

        if options['save']:
            from identity.models import MentalHealthDiagnosis
            MentalHealthDiagnosis.objects.create(
                period_hours=hours,
                tick_count=diag.get('tick_count', 0),
                avg_valence=diag.get('avg_valence', 0),
                avg_arousal=diag.get('avg_arousal', 0),
                negative_ratio=diag.get('negative_ratio', 0),
                dominant_mood=diag.get('dominant_mood', ''),
                negative_streak=diag.get('negative_streak', 0),
                concern_count=diag.get('concern_count', 0),
                diagnosis=diag.get('diagnosis', ''),
                recommendations=diag.get('recommendations', []),
                health_score=score,
                reflection=reflection,
            )
            self.stdout.write(self.style.SUCCESS('Diagnosis saved.'))


def _compute_score(diag):
    """Derive a 0-1 health score from the diagnosis."""
    score = 0.5

    # Valence component (±0.3)
    v = diag.get('avg_valence', 0)
    score += v * 0.3

    # Negative ratio penalty (up to -0.2)
    neg = diag.get('negative_ratio', 0)
    score -= max(0, neg - 0.3) * 0.3

    # Streak penalty (up to -0.15)
    streak = diag.get('negative_streak', 0)
    score -= min(0.15, streak * 0.025)

    # Concern load penalty (up to -0.1)
    concerns = diag.get('concern_count', 0)
    score -= min(0.1, concerns * 0.025)

    return max(0.0, min(1.0, round(score, 3)))

"""Run the Room Planner GA outside the browser for longer searches.

Usage:
    venv/bin/python manage.py roomplanner_evolve --room velour-lab \\
        --generations 500 --population 80 --seed 7

Without --apply the best candidate is printed but NOT saved.
"""
from django.core.management.base import BaseCommand, CommandError

from roomplanner.evolution import apply_result, evolve
from roomplanner.fitness import score_room
from roomplanner.models import Room


class Command(BaseCommand):
    help = "Evolve a lower-penalty layout for a Room Planner room."

    def add_arguments(self, parser):
        parser.add_argument('--room', default='velour-lab',
                            help='Room slug (default: velour-lab)')
        parser.add_argument('--generations', type=int, default=100)
        parser.add_argument('--population',  type=int, default=40)
        parser.add_argument('--seed', type=int, default=None)
        parser.add_argument('--apply', action='store_true',
                            help='Persist the best candidate to the DB.')

    def handle(self, *args, **opts):
        try:
            room = Room.objects.get(slug=opts['room'])
        except Room.DoesNotExist:
            raise CommandError(f"no room with slug {opts['room']!r}")

        before = score_room(room)
        self.stdout.write(
            f"[{room.slug}] before: verdict={before['verdict']} "
            f"penalty={before['total']} "
            f"({len(before['violations'])} violations)"
        )

        result = evolve(
            room,
            generations=opts['generations'],
            population=opts['population'],
            seed=opts['seed'],
        )

        step = max(1, result.generations // 12)
        for i in range(0, len(result.history), step):
            h = result.history[i]
            self.stdout.write(
                f"  gen {h['gen']:4d}: best={h['best']:6d}  mean={h['mean']:6d}"
            )

        self.stdout.write(
            f"[{room.slug}] {result.initial_score} → {result.best_score} "
            f"(improvement {result.improvement})"
        )

        if result.incompatible_with_reality:
            self.stdout.write(self.style.ERROR(
                f"red flag: best candidate still overlaps "
                f"({len(result.overlap)} collision(s)) — NOT saved"
            ))
            for pair in result.overlap:
                self.stdout.write(self.style.ERROR(
                    f"  {pair['a_label']} ↔ {pair['b_label']} "
                    f"({pair['area_cm2']} cm² shared)"
                ))
            return

        if not opts['apply']:
            self.stdout.write(self.style.WARNING(
                "--apply not set — best candidate NOT saved"
            ))
            return

        touched = apply_result(room, result)
        after = score_room(room)
        self.stdout.write(self.style.SUCCESS(
            f"applied: {len(touched)} placements moved. "
            f"verdict now {after['verdict']} (penalty {after['total']})"
        ))

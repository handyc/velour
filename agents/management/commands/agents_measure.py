"""Audit Agent record sizes — checks the 10 KB-per-row design budget.

Reports:
- min/avg/max bio_json bytes
- min/avg/max estimated row bytes
- top-N largest agents
- count over the budget (which would normally fail clean())
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from agents.models import Agent, BIO_BUDGET_BYTES


class Command(BaseCommand):
    help = "Report Agent.bio_json sizes; check the 10K-byte design budget."

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=5)

    def handle(self, *args, **opts):
        agents = list(Agent.objects.all())
        if not agents:
            self.stdout.write('no agents in DB')
            return

        rows = [(a, a.bio_size_bytes(), a.estimated_row_bytes()) for a in agents]
        bios = [b for _, b, _ in rows]
        ests = [e for _, _, e in rows]

        n = len(rows)
        over = sum(1 for b in bios if b > BIO_BUDGET_BYTES)

        self.stdout.write(f'agents: {n}')
        self.stdout.write(
            f'bio_json bytes — min {min(bios)}  avg {sum(bios)//n}  max {max(bios)}'
        )
        self.stdout.write(
            f'estimated row — min {min(ests)}  avg {sum(ests)//n}  max {max(ests)}'
        )
        self.stdout.write(f'budget: {BIO_BUDGET_BYTES} B/bio. over budget: {over}')

        rows.sort(key=lambda r: r[2], reverse=True)
        self.stdout.write(f"\ntop {opts['top']} by estimated row bytes:")
        for a, b, e in rows[:opts['top']]:
            self.stdout.write(f'  {a.slug:30s}  bio={b:5d}  row≈{e:5d}')

"""Load installation-specific Radiant data from a JSON fixture.

The committed `seed_radiant` command produces a neutral demo fleet.
Real installations keep their site-specific data — server names, hosted
project names, vendor-specific candidate SKUs — in an external JSON
file outside the repository.

Fixture schema (all keys optional; missing sections are skipped):

    {
      "servers":           [{name, role, status, ram_gb, ...}],
      "workload_classes":  [{name, typical_ram_mb, ...}],
      "projects":          [{name, server, workload_class, framework, notes} |
                            {placeholder_prefix, count, server,
                             workload_class, framework}],
      "growth_assumptions":[{key, value, unit, description}],
      "candidates":        [{name, purpose, ram_gb, storage_gb, cpu_cores,
                             approximate_cost_eur, monthly_cost_eur, notes}],
      "scenarios":         [{name, description, candidate_names}]
    }

Natural keys:
  Server.name, WorkloadClass.name, HostedProject.name,
  GrowthAssumption.key, Candidate.name, Scenario.name.

All entries use update_or_create so the loader is idempotent.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from radiant.models import (Server, WorkloadClass, HostedProject,
                            GrowthAssumption, Candidate, Scenario)


class Command(BaseCommand):
    help = 'Load Radiant data from a JSON fixture.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Path to JSON fixture file.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Parse and validate without writing.')
        parser.add_argument('--clear', action='store_true',
                            help='Delete all existing Radiant data '
                                 'before loading. Destructive.')

    def handle(self, *args, path, dry_run, clear, **options):
        p = Path(path).expanduser()
        if not p.exists():
            raise CommandError(f'Fixture not found: {p}')
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise CommandError(f'Invalid JSON at {p}: {e}')

        self.stdout.write(f'Loading Radiant fixture from {p}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN — no writes.'))
        if clear and not dry_run:
            self.stdout.write(self.style.WARNING(
                'CLEAR — wiping existing Radiant data'))
            Scenario.objects.all().delete()
            Candidate.objects.all().delete()
            HostedProject.objects.all().delete()
            GrowthAssumption.objects.all().delete()
            WorkloadClass.objects.all().delete()
            Server.objects.all().delete()

        # Servers first (FK target for projects).
        for row in data.get('servers', []):
            self._load_server(row, dry_run)

        # WorkloadClasses next (FK target for projects).
        for row in data.get('workload_classes', []):
            self._load_workload_class(row, dry_run)

        # Projects depend on both.
        for row in data.get('projects', []):
            self._load_project(row, dry_run)

        for row in data.get('growth_assumptions', []):
            self._load_assumption(row, dry_run)

        for row in data.get('candidates', []):
            self._load_candidate(row, dry_run)

        # Scenarios last — they reference Candidates by name.
        for row in data.get('scenarios', []):
            self._load_scenario(row, dry_run)

        self.stdout.write(self.style.SUCCESS('Fixture loaded.'))

    def _load_server(self, row, dry_run):
        name = row['name']
        defaults = {k: v for k, v in row.items() if k != 'name'}
        self.stdout.write(f'server: {name}')
        if not dry_run:
            Server.objects.update_or_create(name=name, defaults=defaults)

    def _load_workload_class(self, row, dry_run):
        name = row['name']
        defaults = {k: v for k, v in row.items() if k != 'name'}
        self.stdout.write(f'class:  {name}')
        if not dry_run:
            WorkloadClass.objects.update_or_create(name=name,
                                                   defaults=defaults)

    def _load_project(self, row, dry_run):
        if row.get('placeholder_prefix'):
            self._load_placeholders(row, dry_run)
            return
        name = row['name']
        server = Server.objects.get(name=row['server'])
        wc = WorkloadClass.objects.get(name=row['workload_class'])
        defaults = {
            'server': server,
            'workload_class': wc,
            'framework': row.get('framework', ''),
            'notes': row.get('notes', ''),
        }
        self.stdout.write(f'proj:   {name}')
        if not dry_run:
            HostedProject.objects.update_or_create(name=name,
                                                   defaults=defaults)

    def _load_placeholders(self, row, dry_run):
        prefix = row['placeholder_prefix']
        count = row['count']
        server = Server.objects.get(name=row['server'])
        wc = WorkloadClass.objects.get(name=row['workload_class'])
        framework = row.get('framework', '')
        self.stdout.write(f'filled: {wc.name} -> {count} '
                          f'"{prefix}-NN" placeholders')
        if dry_run:
            return
        for i in range(1, count + 1):
            HostedProject.objects.update_or_create(
                name=f'{prefix}-{i:02d}',
                defaults={'server': server, 'workload_class': wc,
                          'framework': framework,
                          'notes': 'Placeholder row (loaded via fixture).'})

    def _load_assumption(self, row, dry_run):
        key = row['key']
        defaults = {'value': row['value'],
                    'unit': row.get('unit', ''),
                    'description': row.get('description', '')}
        self.stdout.write(f'assume: {key} = {defaults["value"]} '
                          f'{defaults["unit"]}')
        if not dry_run:
            GrowthAssumption.objects.update_or_create(key=key,
                                                      defaults=defaults)

    def _load_candidate(self, row, dry_run):
        name = row['name']
        defaults = {k: v for k, v in row.items() if k != 'name'}
        self.stdout.write(f'cand:   {name}')
        if not dry_run:
            Candidate.objects.update_or_create(name=name, defaults=defaults)

    def _load_scenario(self, row, dry_run):
        name = row['name']
        defaults = {'description': row.get('description', '')}
        self.stdout.write(f'scen:   {name} '
                          f'({len(row.get("candidate_names", []))} cand.)')
        if dry_run:
            return
        sc, _ = Scenario.objects.update_or_create(name=name, defaults=defaults)
        if 'candidate_names' in row:
            cands = list(Candidate.objects.filter(name__in=row['candidate_names']))
            sc.candidates.set(cands)

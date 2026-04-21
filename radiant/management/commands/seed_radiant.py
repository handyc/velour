"""Seed Radiant with LUCDH's current fleet + workload classes.

Idempotent: re-running updates rows instead of duplicating them.
"""

from django.core.management.base import BaseCommand

from radiant.models import (Server, WorkloadClass, HostedProject,
                            GrowthAssumption)


# Current state as reported by the LUCDH operator, 2026-04-21.
SERVERS = [
    {
        'name': 'LUCDH main',
        'role': 'main',
        'status': 'active',
        'ram_gb': 32,
        'storage_gb': 200,
        'cpu_cores': 8,
        'storage_used_gb': 150,
        'notes': 'Hosts ~40 Django projects and ~30 WordPress class sites.',
    },
    {
        'name': 'OpenAtlas sandbox',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 8,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Isolated because OpenAtlas had installation issues that '
                 'would have entangled other projects.',
    },
    {
        'name': 'SignBank sandbox',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 8,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Isolated for safe code testing of the SignBank refactor '
                 '(open-source sign-language project).',
    },
]


# Workload classes with resource + growth profiles. Numbers are the
# operator's reported baseline; tweak from admin as they refine.
CLASSES = [
    {
        'name': 'Production Django',
        'description': 'Completed humanities projects running 24/7 with '
                       'minimal maintenance.',
        'typical_ram_mb': 100,
        'typical_storage_mb': 500,
        'peak_concurrency': 5,
        'new_per_year': 4.5,
        'saturation_count': 250,
        'notes': 'Anchor class. New requests arrive at ~4-5/year; '
                 'saturation reflects Leiden humanities department size.',
    },
    {
        'name': 'WordPress classroom',
        'description': 'WordPress sites used by live classes, constantly '
                       'updated, peak 40 concurrent students per site.',
        'typical_ram_mb': 250,
        'typical_storage_mb': 800,
        'peak_concurrency': 40,
        'new_per_year': 2.0,
        'saturation_count': 80,
        'notes': 'Different load profile from Django — spiky during '
                 'class hours, near-idle otherwise.',
    },
    {
        'name': 'Experimental isolated',
        'description': 'Special-needs projects kept on their own machines '
                       '(OpenAtlas, SignBank, etc.).',
        'typical_ram_mb': 300,
        'typical_storage_mb': 2000,
        'peak_concurrency': 2,
        'new_per_year': 0.5,
        'saturation_count': 10,
        'notes': 'Low count, high per-project footprint.',
    },
    {
        'name': 'Development',
        'description': 'Projects in active development with changing '
                       'requirements.',
        'typical_ram_mb': 150,
        'typical_storage_mb': 400,
        'peak_concurrency': 2,
        'new_per_year': 3.0,
        'saturation_count': 30,
        'notes': 'Churn-heavy: many rise, some promote to Production, '
                 'others are abandoned.',
    },
    {
        'name': 'Admin / pipeline',
        'description': 'Machines providing full admin access for pipeline '
                       'testing across the fleet.',
        'typical_ram_mb': 500,
        'typical_storage_mb': 5000,
        'peak_concurrency': 1,
        'new_per_year': 0.2,
        'saturation_count': 5,
        'notes': 'One or two boxes is usually enough forever.',
    },
]


# Representative current projects. Not exhaustive — Radiant only needs
# enough to show what it looks like. The operator can edit via admin.
PROJECTS = [
    ('OpenAtlas',          'OpenAtlas sandbox',  'Experimental isolated', 'custom'),
    ('SignBank refactor',  'SignBank sandbox',   'Experimental isolated', 'django'),
]


ASSUMPTIONS = [
    ('storage_drift_mb_per_year', '50', 'MB',
     'Typical drift in storage per project per year of operation.'),
]


class Command(BaseCommand):
    help = 'Seed Radiant with LUCDH current fleet + workload classes.'

    def handle(self, *args, **options):
        for row in SERVERS:
            obj, _ = Server.objects.update_or_create(
                name=row['name'], defaults=row)
            self.stdout.write(f'server: {obj.name}')

        cls_by_name = {}
        for row in CLASSES:
            obj, _ = WorkloadClass.objects.update_or_create(
                name=row['name'], defaults=row)
            cls_by_name[row['name']] = obj
            self.stdout.write(f'class:  {obj.name} '
                              f'({obj.new_per_year}/yr, k={obj.saturation_count})')

        for name, server_name, class_name, fw in PROJECTS:
            server = Server.objects.get(name=server_name)
            wc = cls_by_name[class_name]
            HostedProject.objects.update_or_create(
                name=name, defaults={
                    'server': server, 'workload_class': wc, 'framework': fw,
                })
            self.stdout.write(f'proj:   {name} @ {server_name} / {class_name}')

        # Seed the 40 existing Django projects + 30 WordPress class sites
        # as placeholder "aggregate" rows so current_count matches reality.
        # They're owned by the main server.
        main = Server.objects.get(name='LUCDH main')
        self._populate_placeholders(main, cls_by_name['Production Django'],
                                    'lucdh-django', 40, 'django')
        self._populate_placeholders(main, cls_by_name['WordPress classroom'],
                                    'lucdh-wp', 30, 'wordpress')

        for key, value, unit, description in ASSUMPTIONS:
            GrowthAssumption.objects.update_or_create(
                key=key, defaults={
                    'value': value, 'unit': unit, 'description': description,
                })
            self.stdout.write(f'assume: {key} = {value} {unit}')

        self.stdout.write(self.style.SUCCESS('Radiant seeded.'))

    def _populate_placeholders(self, server, wc, slug_prefix, total, fw):
        current = HostedProject.objects.filter(
            server=server, workload_class=wc,
            slug__startswith=slug_prefix).count()
        for i in range(current + 1, total + 1):
            HostedProject.objects.update_or_create(
                slug=f'{slug_prefix}-{i:03d}',
                defaults={
                    'name': f'{slug_prefix.replace("-", " ")} #{i:03d}',
                    'server': server,
                    'workload_class': wc,
                    'framework': fw,
                })
        self.stdout.write(f'filled: {wc.name} -> {total} placeholders')

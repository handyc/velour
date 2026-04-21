"""Seed Radiant with a neutral demo fleet.

This command ships with Velour and is run on fresh installs. It
populates Radiant with a small, generic example so the forecast and
scenario pages render with meaningful numbers out of the box.

Installation-specific data — real server names, real hosted projects,
real vendor SKUs and prices — belongs in an external fixture loaded
by `load_radiant_fixture <path>`, not in this file. That separation
keeps site-specific information out of the public repository.
"""

from django.core.management.base import BaseCommand

from radiant.models import (Server, WorkloadClass, HostedProject,
                            GrowthAssumption, Candidate, Scenario)


# --- Generic demo servers --------------------------------------------
#
# Three servers: one mixed-production main box and two small sandboxes
# for isolated workloads. No organisation or project names.
SERVERS = [
    {
        'name': 'Primary server',
        'role': 'main',
        'status': 'active',
        'ram_gb': 16,
        'storage_gb': 500,
        'cpu_cores': 4,
        'storage_used_gb': 120,
        'notes': 'Demo: general-purpose box hosting the bulk of the fleet.',
    },
    {
        'name': 'Sandbox alpha',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 4,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Demo: isolated box for a volatile project.',
    },
    {
        'name': 'Sandbox beta',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 4,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Demo: second isolated sandbox.',
    },
]


# --- Generic workload classes ----------------------------------------
#
# The 5 canonical classes Radiant expects, with neutral example
# numbers. Operators tune these via /admin/radiant/.
CLASSES = [
    {
        'name': 'Production web',
        'description': 'Completed web projects running 24/7 with '
                       'minimal maintenance.',
        'typical_ram_mb': 80,
        'typical_storage_mb': 500,
        'peak_concurrency': 5,
        'active_fraction': 0.25,
        'new_per_year': 3.0,
        'saturation_count': 100,
        'notes': 'Anchor class. Sized for a typical dormant web worker.',
    },
    {
        'name': 'Classroom CMS',
        'description': 'CMS sites used by live classes, up to ~30 '
                       'concurrent students when a class is in session.',
        'typical_ram_mb': 60,
        'typical_storage_mb': 500,
        'peak_concurrency': 30,
        'active_fraction': 0.15,
        'new_per_year': 1.0,
        'saturation_count': 40,
        'notes': 'Spiky per-site, but classes rarely collide; only ~15% '
                 'of sites are in session concurrently.',
    },
    {
        'name': 'Experimental isolated',
        'description': 'Projects kept on their own machines because '
                       'installation or runtime risks would entangle '
                       'the main fleet.',
        'typical_ram_mb': 300,
        'typical_storage_mb': 1500,
        'peak_concurrency': 2,
        'active_fraction': 0.5,
        'new_per_year': 0.3,
        'saturation_count': 8,
        'notes': 'Low count, high per-project footprint.',
    },
    {
        'name': 'Development',
        'description': 'Projects in active development.',
        'typical_ram_mb': 80,
        'typical_storage_mb': 400,
        'peak_concurrency': 2,
        'active_fraction': 0.3,
        'new_per_year': 2.0,
        'saturation_count': 20,
        'notes': 'Churn-heavy: some rise to Production, others are '
                 'abandoned.',
    },
    {
        'name': 'Admin / pipeline',
        'description': 'Utility hosts providing admin access and '
                       'pipeline tooling for the fleet.',
        'typical_ram_mb': 300,
        'typical_storage_mb': 3000,
        'peak_concurrency': 1,
        'active_fraction': 1.0,
        'new_per_year': 0.1,
        'saturation_count': 3,
        'notes': 'Sized low in count, high per-machine; usually a '
                 'single box.',
    },
]


# --- Generic candidates + scenarios ----------------------------------
#
# Three purchase-style example boxes at small/medium/large tiers, plus
# two example scenarios. These are intentionally vendor-neutral with
# illustrative prices — real candidates should come from a site
# fixture.
CANDIDATES = [
    {
        'name': 'Example small box',
        'purpose': 'experimental',
        'ram_gb': 16,
        'storage_gb': 250,
        'cpu_cores': 4,
        'approximate_cost_eur': 600,
        'monthly_cost_eur': 0,
        'notes': 'Entry-level example spec. Replace with your own '
                 'vendor catalogue via load_radiant_fixture.',
    },
    {
        'name': 'Example medium box',
        'purpose': 'unified',
        'ram_gb': 64,
        'storage_gb': 1000,
        'cpu_cores': 8,
        'approximate_cost_eur': 2500,
        'monthly_cost_eur': 0,
        'notes': 'Mid-tier example. Comfortable unified replacement.',
    },
    {
        'name': 'Example large box',
        'purpose': 'unified',
        'ram_gb': 128,
        'storage_gb': 4000,
        'cpu_cores': 16,
        'approximate_cost_eur': 5500,
        'monthly_cost_eur': 0,
        'notes': 'High-end example. Future-proof for ~10 years.',
    },
]


SCENARIOS = [
    {
        'name': 'Example unified',
        'description': 'Single medium box replaces the fleet.',
        'candidate_names': ['Example medium box'],
    },
    {
        'name': 'Example future-proof',
        'description': 'Single large box — higher up-front, longer cadence.',
        'candidate_names': ['Example large box'],
    },
]


# A tiny set of placeholder projects so the home page isn't empty.
PROJECT_POPULATION = [
    # (server_name, class_name, prefix, count, framework)
    ('Primary server',  'Production web',        'demo-web',   12, 'django'),
    ('Primary server',  'Classroom CMS',         'demo-cms',    8, 'wordpress'),
    ('Primary server',  'Development',           'demo-dev',    4, 'django'),
    ('Primary server',  'Admin / pipeline',      'demo-admin',  1, 'custom'),
    ('Sandbox alpha',   'Experimental isolated', 'demo-lab-a',  1, 'custom'),
    ('Sandbox beta',    'Experimental isolated', 'demo-lab-b',  1, 'custom'),
]


ASSUMPTIONS = [
    ('storage_drift_mb_per_year', '50', 'MB',
     'Typical drift in storage per project per year of operation.'),
]


class Command(BaseCommand):
    help = ('Seed Radiant with a neutral demo fleet. For real '
            'installation data, use load_radiant_fixture instead.')

    def handle(self, *args, **options):
        for row in SERVERS:
            obj, _ = Server.objects.update_or_create(
                name=row['name'], defaults={k: v for k, v in row.items()
                                            if k != 'name'})
            self.stdout.write(f'server: {obj.name}')

        cls_by_name = {}
        for row in CLASSES:
            obj, _ = WorkloadClass.objects.update_or_create(
                name=row['name'], defaults={k: v for k, v in row.items()
                                            if k != 'name'})
            cls_by_name[obj.name] = obj
            self.stdout.write(f'class:  {obj.name}')

        for server_name, class_name, prefix, count, framework in PROJECT_POPULATION:
            server = Server.objects.get(name=server_name)
            wc = cls_by_name[class_name]
            for i in range(1, count + 1):
                HostedProject.objects.update_or_create(
                    name=f'{prefix}-{i:02d}',
                    defaults={'server': server, 'workload_class': wc,
                              'framework': framework,
                              'notes': 'Demo placeholder.'})
            self.stdout.write(f'filled: {class_name} -> {count} '
                              f'"{prefix}-NN" demo rows')

        for key, value, unit, description in ASSUMPTIONS:
            GrowthAssumption.objects.update_or_create(
                key=key, defaults={'value': value, 'unit': unit,
                                   'description': description})
            self.stdout.write(f'assume: {key} = {value} {unit}')

        for row in CANDIDATES:
            obj, _ = Candidate.objects.update_or_create(
                name=row['name'], defaults={k: v for k, v in row.items()
                                            if k != 'name'})
            self.stdout.write(f'cand:   {obj.name}')

        for row in SCENARIOS:
            sc, _ = Scenario.objects.update_or_create(
                name=row['name'],
                defaults={'description': row.get('description', '')})
            cands = list(Candidate.objects.filter(
                name__in=row.get('candidate_names', [])))
            sc.candidates.set(cands)
            self.stdout.write(f'scen:   {sc.name} ({len(cands)} cand.)')

        self.stdout.write(self.style.SUCCESS(
            'Radiant seeded with demo fleet. '
            'For real data, use: manage.py load_radiant_fixture <path>.'))

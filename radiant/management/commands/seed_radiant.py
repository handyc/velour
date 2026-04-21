"""Seed Radiant with LUCDH's current fleet + workload classes.

Idempotent: re-running updates rows instead of duplicating them.
"""

from django.core.management.base import BaseCommand

from radiant.models import (Server, WorkloadClass, HostedProject,
                            GrowthAssumption, Candidate, Scenario)


# Current state as reported by the LUCDH operator, 2026-04-21.
SERVERS = [
    {
        'name': 'LUCDH main',
        'role': 'main',
        'status': 'active',
        'ram_gb': 8,
        'storage_gb': 200,
        'cpu_cores': 4,
        'storage_used_gb': 150,
        'notes': 'Hosts ~40 Django projects and ~30 WordPress class sites '
                 'on 8 GB RAM / 4 cores. Realistic peak already exceeds '
                 'available RAM — fleet survives because classes rarely '
                 'collide and most projects sit idle at baseline.',
    },
    {
        'name': 'OpenAtlas sandbox',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 2,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Isolated because OpenAtlas had installation issues that '
                 'would have entangled other projects. 2 GB RAM.',
    },
    {
        'name': 'SignBank sandbox',
        'role': 'experimental',
        'status': 'active',
        'ram_gb': 2,
        'storage_gb': 100,
        'cpu_cores': 2,
        'notes': 'Isolated for safe code testing of the SignBank refactor '
                 '(open-source sign-language project). 2 GB RAM.',
    },
]


# Workload classes with resource + growth profiles. Numbers are the
# operator's reported baseline; tweak from admin as they refine.
CLASSES = [
    {
        'name': 'Production Django',
        'description': 'Completed humanities projects running 24/7 with '
                       'minimal maintenance.',
        'typical_ram_mb': 70,
        'typical_storage_mb': 500,
        'peak_concurrency': 5,
        'active_fraction': 0.20,
        'new_per_year': 4.5,
        'saturation_count': 250,
        'notes': 'Anchor class. Low-traffic humanities sites rarely '
                 'peak together; only ~20% are active at any moment. '
                 'Idle Django + gunicorn worker sits at ~70 MB.',
    },
    {
        'name': 'WordPress classroom',
        'description': 'WordPress sites used by live classes, constantly '
                       'updated, up to 40 students on a single site when '
                       'a class is in session.',
        'typical_ram_mb': 60,
        'typical_storage_mb': 800,
        'peak_concurrency': 40,
        'active_fraction': 0.15,
        'new_per_year': 2.0,
        'saturation_count': 80,
        'notes': 'Spiky per-site, but classes are staggered; only ~15% '
                 'of sites are in session concurrently at peak. Idle '
                 'PHP-FPM pool sits at ~60 MB — workers die between '
                 'requests, so dormant sites cost almost nothing.',
    },
    {
        'name': 'Experimental isolated',
        'description': 'Special-needs projects kept on their own machines '
                       '(OpenAtlas, SignBank, etc.).',
        'typical_ram_mb': 300,
        'typical_storage_mb': 2000,
        'peak_concurrency': 2,
        'active_fraction': 0.5,
        'new_per_year': 0.5,
        'saturation_count': 10,
        'notes': 'Low count, high per-project footprint.',
    },
    {
        'name': 'Development',
        'description': 'Projects in active development with changing '
                       'requirements.',
        'typical_ram_mb': 80,
        'typical_storage_mb': 400,
        'peak_concurrency': 2,
        'active_fraction': 0.3,
        'new_per_year': 3.0,
        'saturation_count': 30,
        'notes': 'Churn-heavy: many rise, some promote to Production, '
                 'others are abandoned.',
    },
    {
        'name': 'Admin / pipeline',
        'description': 'Machines providing full admin access for pipeline '
                       'testing across the fleet.',
        'typical_ram_mb': 300,
        'typical_storage_mb': 5000,
        'peak_concurrency': 1,
        'active_fraction': 1.0,
        'new_per_year': 0.2,
        'saturation_count': 5,
        'notes': 'One or two boxes is usually enough forever.',
    },
]


# Candidate hardware options under consideration for May 2026 purchase.
# Prices are rough retail figures the operator can refine.
CANDIDATES = [
    {
        'name': 'Mini prod box (64 GB / 1 TB / 6-core)',
        'purpose': 'django',
        'ram_gb': 64,
        'storage_gb': 1000,
        'cpu_cores': 6,
        'approximate_cost_eur': 2000,
        'notes': 'Budget mini-tower with ECC RAM; enough for current '
                 'Django load plus ~5 years of growth.',
    },
    {
        'name': 'Mini WP box (32 GB / 500 GB / 6-core)',
        'purpose': 'wordpress',
        'ram_gb': 32,
        'storage_gb': 500,
        'cpu_cores': 6,
        'approximate_cost_eur': 1500,
        'notes': 'Dedicated to classroom WordPress; smaller RAM because '
                 'only a handful of classes hit peak at once.',
    },
    {
        'name': 'Unified modest (96 GB / 2 TB / 8-core)',
        'purpose': 'unified',
        'ram_gb': 96,
        'storage_gb': 2000,
        'cpu_cores': 8,
        'approximate_cost_eur': 3500,
        'notes': 'Single replacement box — simpler ops, still on a '
                 '~5-year replacement cadence.',
    },
    {
        'name': 'Unified comfortable (128 GB / 4 TB / 12-core)',
        'purpose': 'unified',
        'ram_gb': 128,
        'storage_gb': 4000,
        'cpu_cores': 12,
        'approximate_cost_eur': 5500,
        'notes': 'More headroom; should carry the fleet for ~7-10 years '
                 'without a second purchase.',
    },
    {
        'name': 'Shoestring refurb (16 GB / 500 GB / 4-core)',
        'purpose': 'unified',
        'ram_gb': 16,
        'storage_gb': 500,
        'cpu_cores': 4,
        'approximate_cost_eur': 600,
        'notes': 'Used / refurb option. Matches current capacity on a '
                 'bigger disk — survives ~2 years before a squeeze.',
    },
    {
        'name': 'Pi-class experimental (8 GB / 500 GB / 4-core)',
        'purpose': 'experimental',
        'ram_gb': 8,
        'storage_gb': 500,
        'cpu_cores': 4,
        'approximate_cost_eur': 300,
        'notes': 'Tiny SBC-style box for the next OpenAtlas-style '
                 'isolation need. Cheap + disposable.',
    },
]


SCENARIOS = [
    {
        'name': 'Tight budget — refurb and hold',
        'description': 'Shoestring refurb as the main replacement; no '
                       'WP split. Buys ~2 years before squeeze.',
        'candidate_slugs': ['shoestring-refurb-16-gb-500-gb-4-core'],
    },
    {
        'name': 'Mid — unified modest',
        'description': 'One 96 GB / 2 TB box. Simpler ops, 5-year '
                       'headroom, single point of failure.',
        'candidate_slugs': ['unified-modest-96-gb-2-tb-8-core'],
    },
    {
        'name': 'Split prod vs WP',
        'description': 'Django/prod on mini prod box; WP classroom on '
                       'dedicated mini WP box. Isolates class spikes.',
        'candidate_slugs': [
            'mini-prod-box-64-gb-1-tb-6-core',
            'mini-wp-box-32-gb-500-gb-6-core',
        ],
    },
    {
        'name': 'Three-box split (prod + WP + experimental)',
        'description': 'Matches current LUCDH topology: production Django, '
                       'classroom WordPress, wildly-experimental isolated. '
                       'Replaces the two 2 GB sandboxes with one shared '
                       'Pi-class box. Three independent failure domains.',
        'candidate_slugs': [
            'mini-prod-box-64-gb-1-tb-6-core',
            'mini-wp-box-32-gb-500-gb-6-core',
            'pi-class-experimental-8-gb-500-gb-4-core',
        ],
    },
    {
        'name': 'Comfortable — future-proof single',
        'description': '128 GB / 4 TB unified box for ~7-10 year cadence. '
                       'Higher up-front cost; fewer purchases over time.',
        'candidate_slugs': ['unified-comfortable-128-gb-4-tb-12-core'],
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

        cand_by_slug = {}
        for row in CANDIDATES:
            obj, _ = Candidate.objects.update_or_create(
                name=row['name'], defaults=row)
            cand_by_slug[obj.slug] = obj
            self.stdout.write(f'cand:   {obj.name}')

        for row in SCENARIOS:
            slugs = row.pop('candidate_slugs')
            scenario, _ = Scenario.objects.update_or_create(
                name=row['name'], defaults={
                    'description': row['description'],
                })
            scenario.candidates.set([cand_by_slug[s] for s in slugs
                                     if s in cand_by_slug])
            self.stdout.write(f'scen:   {scenario.name} '
                              f'({scenario.candidates.count()} candidate(s))')

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

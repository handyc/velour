"""Seed default Conduit targets: local shell + ALICE manual-submit."""

from django.core.management.base import BaseCommand

from conduit.models import JobTarget


DEFAULTS = [
    dict(
        slug='local-shell',
        name='Local shell',
        kind='local',
        host='localhost',
        priority=10,
        config={},
        notes='The Velour web-process uid. No sandbox — single-user '
              'assumption.',
    ),
    dict(
        slug='alice-manual',
        name='ALICE (Leiden HPC, manual submit)',
        kind='slurm_manual',
        host='login1.alice.universiteitleiden.nl',
        priority=5,
        config={
            'ssh_user':   'username',
            'partition':  'cpu-short',
            'remote_dir': '~/jobs',
            'account':    '',
        },
        notes='ALICE prohibits automated sbatch; human operator '
              'submits via handoff queue.',
    ),
]


class Command(BaseCommand):
    help = 'Seed default Conduit JobTargets (idempotent).'

    def handle(self, *args, **options):
        for spec in DEFAULTS:
            slug = spec['slug']
            obj, created = JobTarget.objects.update_or_create(
                slug=slug, defaults=spec)
            verb = 'created' if created else 'refreshed'
            self.stdout.write(f'{verb}: {obj}')

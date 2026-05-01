"""Bundle a HexNN HPC run as a Conduit JobHandoff for ALICE.

ALICE prohibits automated sbatch, so this command does the *Velour*
half of the workflow: render the sbatch template with the parameters
the user picked, point at the right artifact path on the cluster, and
materialise a `JobHandoff` row with copy-paste instructions. A human
operator takes the handoff from there: scp the script, sbatch it,
paste back the Slurm job ID.

Variants:

  --variant cpu       Multi-CPU only (multiprocessing.Pool, Python).
                      Working. Single-node up to ~64 cores.
  --variant islands   Portable C engine + MPI islands across many
                      nodes (up to 288 cores on ALICE). Working —
                      builds engine.c + mpi_islands.c on the cluster
                      via mpicc, runs N ranks with a chosen merge
                      strategy.
  --variant gpu       GPU-only (cupy). Planned — emits a stub handoff
                      pointing at the not-yet-built gpu.py / gpu.sbatch.
  --variant hybrid    GPU + CPU hybrid. Planned — same stub treatment.

Default values track ALICE's `cpu-short` partition (1h limit, 64
cores, 4G/cpu mem).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from conduit.executors import dispatch
from conduit.models import Job, JobTarget


VARIANTS = {
    'cpu': {
        'sbatch_template': 'isolation/artifacts/hexnn_search/hpc/cpu.sbatch',
        'driver_files':    ['isolation/artifacts/hexnn_search/hpc/cpu.py',
                            'isolation/artifacts/hexnn_search/pi4.py'],
        'status':          'working',
    },
    'islands': {
        'sbatch_template': 'isolation/artifacts/hexnn_search/engine_c/islands.sbatch',
        'driver_files':    ['isolation/artifacts/hexnn_search/engine_c/engine.h',
                            'isolation/artifacts/hexnn_search/engine_c/engine.c',
                            'isolation/artifacts/hexnn_search/engine_c/mpi_islands.c',
                            'isolation/artifacts/hexnn_search/engine_c/Makefile'],
        'status':          'working',
    },
    'gpu': {
        'sbatch_template': None,
        'driver_files':    [],
        'status':          'planned',
    },
    'hybrid': {
        'sbatch_template': None,
        'driver_files':    [],
        'status':          'planned',
    },
}


def _render_cpu_sbatch(template_path: Path, *, partition: str,
                       time_limit: str, nodes: int, cpus_per_task: int,
                       mem: str, account: str, remote_dir: str,
                       K: int, n_log2: int, grid: int, steps: int,
                       burn_in: int, pop: int, gens: int, rate: float,
                       seed: int, output_path: str) -> str:
    text = template_path.read_text()
    account_line = f'#SBATCH --account={account}' if account else ''
    return text.format(
        partition=partition, time_limit=time_limit, nodes=nodes,
        cpus_per_task=cpus_per_task, mem=mem, account_line=account_line,
        remote_dir=remote_dir, K=K, n_log2=n_log2, grid=grid,
        steps=steps, burn_in=burn_in, pop=pop, gens=gens, rate=rate,
        seed=seed, output_path=output_path,
    )


def _render_islands_sbatch(template_path: Path, *, partition: str,
                           time_limit: str, nodes: int, ntasks: int,
                           cpus_per_task: int, mem_per_cpu: str,
                           account: str, remote_dir: str,
                           K: int, n_log2: int, grid: int, steps: int,
                           burn_in: int, pop_per_island: int,
                           gens_per_epoch: int, epochs: int, rate: float,
                           seed: int, merge_strategy: str,
                           diversity_threshold: int,
                           output_path: str) -> str:
    text = template_path.read_text()
    account_line = f'#SBATCH --account={account}' if account else ''
    return text.format(
        partition=partition, time_limit=time_limit, nodes=nodes,
        ntasks=ntasks, cpus_per_task=cpus_per_task,
        mem_per_cpu=mem_per_cpu, account_line=account_line,
        remote_dir=remote_dir, K=K, n_log2=n_log2, grid=grid,
        steps=steps, burn_in=burn_in,
        pop_per_island=pop_per_island, gens_per_epoch=gens_per_epoch,
        epochs=epochs, rate=rate, seed=seed,
        merge_strategy=merge_strategy,
        diversity_threshold=diversity_threshold,
        output_path=output_path,
    )


class Command(BaseCommand):
    help = 'Submit a HexNN HPC run via Conduit (manual ALICE handoff).'

    def add_arguments(self, parser):
        parser.add_argument('--variant', choices=list(VARIANTS), default='cpu')
        parser.add_argument('--target',  default='alice-manual',
                            help='Conduit JobTarget slug.')
        # Slurm
        parser.add_argument('--partition',     default='cpu-short')
        parser.add_argument('--time-limit',    default='01:00:00')
        parser.add_argument('--nodes',         type=int, default=1)
        parser.add_argument('--cpus-per-task', type=int, default=64,
                            help='Workers in the pool. Up to ~64 for a '
                                 'single ALICE compute node; more needs '
                                 'MPI not multiprocessing.')
        parser.add_argument('--mem',           default='32G')
        parser.add_argument('--account',       default='')
        parser.add_argument('--remote-dir',    default='~/jobs/hexnn-hpc',
                            help='ALICE-side directory; the sbatch template '
                                 'cd-s here before running.')
        # GA
        parser.add_argument('--k',       type=int, default=4)
        parser.add_argument('--n-log2',  type=int, default=14)
        parser.add_argument('--grid',    type=int, default=16)
        parser.add_argument('--steps',   type=int, default=80)
        parser.add_argument('--burn-in', type=int, default=20)
        parser.add_argument('--pop',     type=int, default=128)
        parser.add_argument('--gens',    type=int, default=60)
        parser.add_argument('--rate',    type=float, default=0.0005)
        parser.add_argument('--seed',    type=int, default=1)
        parser.add_argument('--output',  default='hexnn_winner.json')
        parser.add_argument('--name',    default='',
                            help='Friendly name for the Conduit Job.')
        # Islands-only flags. Ignored for variant=cpu but parsed
        # uniformly to keep the CLI orthogonal.
        parser.add_argument('--ntasks',           type=int, default=16,
                            help='[islands] number of MPI ranks = islands.')
        parser.add_argument('--mem-per-cpu',      default='4G',
                            help='[islands] per-CPU memory; ALICE prefers '
                                 '--mem-per-cpu over --mem for ntasks>1.')
        parser.add_argument('--pop-per-island',   type=int, default=64)
        parser.add_argument('--gens-per-epoch',   type=int, default=30)
        parser.add_argument('--epochs',           type=int, default=20)
        parser.add_argument('--merge-strategy',
                            choices=('migrate-best', 'crossover-merge',
                                     'tournament-merge', 'diversity-filter'),
                            default='migrate-best',
                            help='[islands] inter-island merge strategy.')
        parser.add_argument('--diversity-threshold', type=int, default=100,
                            help='[islands] for diversity-filter — minimum '
                                 'Hamming distance to accept a peer elite.')

    def handle(self, **opts):
        variant = VARIANTS[opts['variant']]
        if variant['status'] != 'working':
            raise CommandError(
                f"variant '{opts['variant']}' is {variant['status']} — "
                f'see isolation/artifacts/hexnn_search/hpc/README.md.')

        try:
            target = JobTarget.objects.get(slug=opts['target'])
        except JobTarget.DoesNotExist:
            raise CommandError(
                f"Conduit target '{opts['target']}' not found. Run "
                f'`manage.py seed_conduit_defaults` first.')

        base_dir = Path(settings.BASE_DIR)
        template_path = base_dir / variant['sbatch_template']
        if not template_path.is_file():
            raise CommandError(f'sbatch template missing: {template_path}')

        if opts['variant'] == 'islands':
            script = _render_islands_sbatch(
                template_path,
                partition=opts['partition'], time_limit=opts['time_limit'],
                nodes=opts['nodes'], ntasks=opts['ntasks'],
                cpus_per_task=opts['cpus_per_task'],
                mem_per_cpu=opts['mem_per_cpu'],
                account=opts['account'],
                remote_dir=opts['remote_dir'],
                K=opts['k'], n_log2=opts['n_log2'], grid=opts['grid'],
                steps=opts['steps'], burn_in=opts['burn_in'],
                pop_per_island=opts['pop_per_island'],
                gens_per_epoch=opts['gens_per_epoch'],
                epochs=opts['epochs'], rate=opts['rate'],
                seed=opts['seed'],
                merge_strategy=opts['merge_strategy'],
                diversity_threshold=opts['diversity_threshold'],
                output_path=opts['output'],
            )
        else:
            script = _render_cpu_sbatch(
                template_path,
                partition=opts['partition'], time_limit=opts['time_limit'],
                nodes=opts['nodes'], cpus_per_task=opts['cpus_per_task'],
                mem=opts['mem'], account=opts['account'],
                remote_dir=opts['remote_dir'],
                K=opts['k'], n_log2=opts['n_log2'], grid=opts['grid'],
                steps=opts['steps'], burn_in=opts['burn_in'],
                pop=opts['pop'], gens=opts['gens'], rate=opts['rate'],
                seed=opts['seed'], output_path=opts['output'],
            )

        # Driver-file copy instructions: every script the sbatch will
        # invoke needs to land in --remote-dir before submission.
        copy_lines = []
        for rel in variant['driver_files']:
            copy_lines.append(
                f'scp {rel} '
                f'{(target.config or {}).get("ssh_user", "username")}@'
                f'{target.host or "alice"}:{opts["remote_dir"]}/'
                f'{Path(rel).name}'
            )
        copy_block = '\n'.join(copy_lines)

        name = opts['name'] or (
            f'HexNN HPC {opts["variant"]} · pop={opts["pop"]} '
            f'gens={opts["gens"]} cpus={opts["cpus_per_task"]}'
        )
        slug = (f'hexnn-hpc-{opts["variant"]}-pop{opts["pop"]}-'
                f'g{opts["gens"]}-c{opts["cpus_per_task"]}')

        job = Job(
            slug=slug[:200],
            name=name,
            kind='slurm_script',
            requested_target=target,
            payload={
                'script':       script,
                'cluster_hint': target.slug,
                'extra_setup': (
                    '# Make sure the driver scripts are on the cluster\n'
                    '# before sbatch runs:\n'
                    f'mkdir -p {opts["remote_dir"]}\n'
                    f'{copy_block}'
                ),
            },
        )
        # Slug uniqueness: append a counter if needed.
        existing = set(Job.objects.filter(slug__startswith=slug)
                                  .values_list('slug', flat=True))
        if job.slug in existing:
            n = 2
            while f'{slug}-{n}' in existing:
                n += 1
            job.slug = f'{slug}-{n}'
        job.save()

        dispatch(job)
        job.refresh_from_db()

        self.stdout.write(self.style.SUCCESS(
            f'+ Conduit Job: {job.slug}  ({job.get_status_display()})'))
        if job.status == 'handoff':
            handoff = job.handoff
            self.stdout.write('  Handoff materialised. To complete the run:')
            self.stdout.write('  ' + '\n  '.join(
                handoff.submit_instructions.strip().splitlines()))
            self.stdout.write('  Pre-sbatch driver-file copy:')
            for line in copy_block.splitlines():
                self.stdout.write(f'    {line}')
        else:
            self.stdout.write(f'  status: {job.get_status_display()}')
            if job.stderr:
                self.stdout.write(f'  stderr: {job.stderr}')

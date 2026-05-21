"""One-button continuous-training step for ALICE Shakespeare runs.

  manage.py caformer_alice_step

Performs a full cycle:

  1. Scan conduit/alice/bundles/ for bundles with --kind in their
     manifest matching the requested kind (default: shakespeare).
  2. For each bundle that has outputs/ but no INGESTED.txt marker:
       - pull latest outputs from ALICE
       - run alice_ingest_cell8 <slug>
       - drop an INGESTED.txt marker
  3. Report corpus state.
  4. If partial pairs remain (and --no-regen not set), generate the
     NEXT bundle automatically with the next version number; print
     the one-line ssh command the user runs on ALICE.

Flags:
  --kind         shakespeare | all          (default shakespeare)
  --base-slug    bundle slug prefix          (default cell8-shakespeare-v)
  --no-pull      skip remote pull / ingest
  --no-regen     skip next-bundle generation
  --max-seconds-per-pos
                 per-position budget for the NEXT bundle (default
                 auto-doubles each version)

User experience target:

  on LOCAL:  venv/bin/python manage.py caformer_alice_step
             # prints:  ssh handyca@alice 'cd ~/velour-dev/.alice_bundles/cell8-shakespeare-v4 && sbatch submit.sh'
  on ALICE:  (paste that line)
  next day:  venv/bin/python manage.py caformer_alice_step  again
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = ('One-button cycle: pull → ingest → report → regenerate '
            'next bundle.  Single command per local turn.')

    def add_arguments(self, parser):
        parser.add_argument('--kind', default='shakespeare',
                              choices=['shakespeare', 'all'])
        parser.add_argument('--base-slug', default='cell8-shakespeare-v')
        parser.add_argument('--no-pull', action='store_true',
                              help='skip rsync pull from ALICE')
        parser.add_argument('--no-regen', action='store_true',
                              help='do not generate next bundle')
        parser.add_argument('--max-seconds-per-pos', type=float, default=0.0,
                              help='override per-pos budget for next '
                                     'bundle (0 = auto-double per version)')
        parser.add_argument('--positions-per-task', type=int, default=4)

    def handle(self, *, kind, base_slug, no_pull, no_regen,
                 max_seconds_per_pos, positions_per_task, **opts):
        def log(msg):
            sys.stdout.write(str(msg) + '\n'); sys.stdout.flush()

        base = Path(settings.BASE_DIR)
        bundles_dir = base / 'conduit' / 'alice' / 'bundles'

        # ── 1. Discover existing bundles matching base_slug ───────
        bundles = []
        if bundles_dir.exists():
            for b in sorted(bundles_dir.iterdir()):
                if not b.is_dir(): continue
                if not b.name.startswith(base_slug): continue
                m = re.match(rf'^{re.escape(base_slug)}(\d+)$', b.name)
                if not m: continue
                # Read manifest to know the expected array size — used
                # to detect partial / still-running bundles.
                expected = 0
                manifest_path = b / 'manifest.json'
                if manifest_path.exists():
                    try:
                        expected = int(json.loads(
                            manifest_path.read_text()).get('array_size', 0))
                    except (json.JSONDecodeError, OSError, ValueError):
                        pass
                outputs_dir = b / 'outputs'
                n_rules = (len(list(outputs_dir.glob('*.rules')))
                           if outputs_dir.is_dir() else 0)
                bundles.append({
                    'slug':        b.name,
                    'version':     int(m.group(1)),
                    'path':        b,
                    'has_outputs': n_rules > 0,
                    'n_rules':     n_rules,
                    'expected':    expected,
                    'complete':    expected > 0 and n_rules >= expected,
                    'ingested':    (b / 'INGESTED.txt').exists(),
                })
        bundles.sort(key=lambda b: b['version'])

        log(f'=== caformer_alice_step ({kind}) ===')
        log(f'  bundles_dir: {bundles_dir}')
        log(f'  existing bundles: {len(bundles)}')
        for b in bundles:
            tags = []
            tags.append(f"{b['n_rules']}/{b['expected'] or '?'} rules")
            if b['complete']: tags.append('complete')
            if b['ingested']: tags.append('ingested')
            log(f"    v{b['version']:>2}  {b['slug']:<30}  "
                f"{', '.join(tags)}")

        # ── 2. Pull + ingest any COMPLETED bundle ──────────────
        # Crucially: skip ingest if the bundle isn't yet complete on
        # ALICE (e.g. v3 still running while v4 sits in the queue).
        # Without this check we'd ingest a partial bundle, mark it
        # done, and never come back for the rest.
        for b in bundles:
            if b['ingested']:
                continue
            if not no_pull:
                pull_sh = b['path'] / 'pull.sh'
                if pull_sh.exists():
                    log(f"")
                    log(f"-- pulling {b['slug']} from ALICE --")
                    try:
                        subprocess.run(
                            ['bash', str(pull_sh)], check=True, cwd=str(base))
                    except subprocess.CalledProcessError as e:
                        log(f"  rsync failed: {e} — skipping ingest")
                        continue
                    # Refresh counts after pull.
                    outputs_dir = b['path'] / 'outputs'
                    b['n_rules'] = (len(list(outputs_dir.glob('*.rules')))
                                    if outputs_dir.is_dir() else 0)
                    b['has_outputs'] = b['n_rules'] > 0
                    b['complete'] = (b['expected'] > 0
                                     and b['n_rules'] >= b['expected'])
            if not b['has_outputs']:
                log(f"  {b['slug']}: no .rules files yet — leaving "
                    f"un-ingested (likely still queued on ALICE)")
                continue
            if not b['complete']:
                log(f"  {b['slug']}: PARTIAL "
                    f"({b['n_rules']}/{b['expected']} rules) — still "
                    f"running on ALICE.  Skipping ingest so we can "
                    f"re-pull when it finishes.")
                continue
            log(f"")
            log(f"-- ingesting {b['slug']} "
                f"({b['n_rules']}/{b['expected']} rules — complete) --")
            try:
                call_command('alice_ingest_cell8', b['slug'])
                (b['path'] / 'INGESTED.txt').write_text(
                    f"ingested via caformer_alice_step\n"
                    f"n_rules={b['n_rules']} expected={b['expected']}\n")
                b['ingested'] = True
            except Exception as e:                  # noqa: BLE001
                log(f"  ingest failed: {e}")

        # ── 3. Corpus state ─────────────────────────────────────
        from caformer.models import QRPair
        exact_filter = (Q(cell8_b008_exact=True) | Q(cell8_b016_exact=True)
                        | Q(cell8_b032_exact=True) | Q(cell8_b064_exact=True)
                        | Q(cell8_b128_exact=True) | Q(cell8_b256_exact=True))
        if kind == 'shakespeare':
            qs = QRPair.objects.filter(id__gte=73, id__lte=155)
        else:
            qs = QRPair.objects.all()
        total = qs.count()
        exact = qs.filter(exact_filter).count()
        partial = total - exact
        log(f"")
        log(f"-- corpus state ({kind}) --")
        log(f"  total:       {total}")
        log(f"  byte-exact:  {exact}")
        log(f"  partial:     {partial}")
        if partial == 0:
            log(self.style.SUCCESS(
                "  ✓ all pairs are byte-exact — corpus is fully trained"))
            return

        if no_regen:
            log("")
            log("(--no-regen passed; not generating next bundle)")
            return

        # ── 4. Generate the next bundle ─────────────────────────
        next_version = (bundles[-1]['version'] + 1) if bundles else 3
        next_slug = f'{base_slug}{next_version}'
        # Auto-double per-pos budget per version (1500 → 3000 → 6000 → …),
        # capped at 12000 (= 3.3 h with positions_per_task=1).
        if max_seconds_per_pos <= 0:
            budget = min(12000, 1500 * (2 ** (next_version - 2)))
        else:
            budget = max_seconds_per_pos
        log(f"")
        log(f"-- generating next bundle: {next_slug} --")
        log(f"  per-pos budget: {budget:.0f} s "
            f"(auto-doubled from v{next_version - 1})")
        try:
            call_command(
                'caformer_alice_retry_partial',
                kind=kind, slug=next_slug,
                max_seconds_per_pos=budget,
                positions_per_task=positions_per_task,
                time_limit='03:50:00',
                mem_per_task='4G',
                ssh_host='alice',
                ssh_user='handyca',
                dry_run=False,
            )
        except Exception as e:                      # noqa: BLE001
            log(f"  bundle generation failed: {e}")
            return

        # ── 5. Push + print the sbatch line ─────────────────────
        push_sh = bundles_dir / next_slug / 'push.sh'
        if push_sh.exists() and not no_pull:
            log("")
            log(f"-- pushing {next_slug} to ALICE --")
            try:
                subprocess.run(
                    ['bash', str(push_sh)], check=True, cwd=str(base))
            except subprocess.CalledProcessError as e:
                log(f"  push failed: {e}")
                return

        log("")
        log(self.style.SUCCESS(
            f"=== one-step done.  ON ALICE, run: ===\n"
            f"  ssh handyca@alice 'cd ~/velour-dev/.alice_bundles/"
            f"{next_slug} && sbatch submit.sh'\n"
            f"=== then come back next cycle and run "
            f"manage.py caformer_alice_step again ==="))

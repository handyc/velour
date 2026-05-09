"""Scan isolation/artifacts/office for officerpg build files and
upsert Build rows for each.  Idempotent — re-runs update file_path
+ bytes_size + git_commit without creating duplicates."""
import os
import re
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand

from bidir.models import Build, Variant


# officerpghiresev<N>.html — the canonical js-html chain.  Ignore
# experimental siblings like officerpghirestest / officerpghiresga
# unless the user tags them later.
RE_JSHTML = re.compile(r'^officerpghires(ev\d+)\.html$')

# A future officerpg.c family.  Not currently present, but the
# scanner is ready to ingest it once builds land at e.g.
# isolation/artifacts/office/officerpgc/v0.1/officerpg.c, etc.
ANSI_C_DIR = os.path.join('isolation', 'artifacts', 'office', 'officerpgc')


def _last_commit_for(rel_path):
    """Return the SHA of the most recent commit that touched `rel_path`,
    or '' if git isn't available or the path is unknown."""
    try:
        out = subprocess.run(
            ['git', 'log', '-n', '1', '--pretty=%H', '--', rel_path],
            cwd=settings.BASE_DIR,
            capture_output=True, text=True, timeout=10,
        )
        return (out.stdout or '').strip()[:40]
    except Exception:
        return ''


class Command(BaseCommand):
    help = ('Scan officerpg js-html and ansi-c artifact directories '
            'and upsert bidir Build rows for each fork found.')

    def add_arguments(self, parser):
        parser.add_argument(
            '--prune', action='store_true',
            help='Delete Build rows whose file_path no longer exists.')

    def handle(self, *args, **opts):
        v_js = Variant.objects.filter(slug='js-html').first()
        v_c  = Variant.objects.filter(slug='ansi-c').first()
        if not v_js:
            self.stderr.write(
                'Run "manage.py seed_bidir" first — no js-html Variant.')
            return

        seen_paths = set()
        scanned = 0

        # ── js-html chain ───────────────────────────────────────────
        js_dir_rel = os.path.join('isolation', 'artifacts', 'office')
        js_dir_abs = os.path.join(settings.BASE_DIR, js_dir_rel)
        if os.path.isdir(js_dir_abs):
            for fn in sorted(os.listdir(js_dir_abs)):
                m = RE_JSHTML.match(fn)
                if not m:
                    continue
                label = m.group(1)
                rel = os.path.join(js_dir_rel, fn)
                abs_ = os.path.join(settings.BASE_DIR, rel)
                size = os.path.getsize(abs_)
                commit = _last_commit_for(rel)
                _, created = Build.objects.update_or_create(
                    variant=v_js, label=label,
                    defaults={
                        'file_path':  rel,
                        'git_commit': commit,
                        'bytes_size': size,
                    },
                )
                seen_paths.add(rel)
                scanned += 1
                marker = '+' if created else '·'
                self.stdout.write(
                    f'{marker} {v_js.slug}/{label}  {size:,} B  '
                    f'{commit[:8] if commit else "—"}')

        # ── ansi-c chain (forward-compat) ───────────────────────────
        # bytes_size for the C builds is the COMPILED BINARY size
        # (officerpg next to officerpg.c) when present — that's the
        # number we care about against the 64 KB cap.  Falls back to
        # the source size when the binary hasn't been built yet.
        c_dir_abs = os.path.join(settings.BASE_DIR, ANSI_C_DIR)
        if v_c and os.path.isdir(c_dir_abs):
            for entry in sorted(os.listdir(c_dir_abs)):
                sub = os.path.join(c_dir_abs, entry)
                if not os.path.isdir(sub):
                    continue
                main_c = os.path.join(sub, 'officerpg.c')
                if not os.path.isfile(main_c):
                    continue
                # Prefer the compiled binary's size when available.
                bin_path = os.path.join(sub, 'officerpg')
                if os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
                    size_path = bin_path
                    rel = os.path.join(ANSI_C_DIR, entry, 'officerpg')
                else:
                    size_path = main_c
                    rel = os.path.join(ANSI_C_DIR, entry, 'officerpg.c')
                size = os.path.getsize(size_path)
                commit = _last_commit_for(
                    os.path.join(ANSI_C_DIR, entry, 'officerpg.c'))
                _, created = Build.objects.update_or_create(
                    variant=v_c, label=entry,
                    defaults={
                        'file_path':  rel,
                        'git_commit': commit,
                        'bytes_size': size,
                    },
                )
                seen_paths.add(rel)
                scanned += 1
                marker = '+' if created else '·'
                self.stdout.write(
                    f'{marker} {v_c.slug}/{entry}  {size:,} B  '
                    f'{commit[:8] if commit else "—"}')

        if opts.get('prune'):
            stale = Build.objects.exclude(file_path__in=seen_paths)
            n_stale = stale.count()
            if n_stale:
                stale.delete()
                self.stdout.write(self.style.WARNING(
                    f'pruned {n_stale} stale Build rows'))

        self.stdout.write(self.style.SUCCESS(f'{scanned} builds scanned'))

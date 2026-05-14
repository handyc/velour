"""Stream-import the Ghanaian Sign Language Lexicon directly from
the Zenodo zip (no extraction needed).

  Fragkiadakis, M., Nyst, V., Nyarko, M. (2021).
  Ghanaian Sign Language Lexicon (OpenPose data).
  Zenodo. https://doi.org/10.5281/zenodo.4533753
  CC-BY-4.0

Reads each per-sign directory inside the archive, runs the
OpenPose retargeter on every frame JSON, and creates one Sign row
plus one Frame row per video frame.

Usage:
  manage.py import_gsl_lexicon signs/imports/GSL_openpose_data.zip [--limit N] [--variety NAME]
"""

from __future__ import annotations
import io
import json
import time
import zipfile
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from signs.models import Language, Variety, Lemma, Sign, Frame, Source
from signs import openpose


ROOT_DIR = 'GSL_openpose_data'


def _signs_in_zip(zf: zipfile.ZipFile) -> dict[str, list[str]]:
    """Return {sign_name: [frame_json_paths sorted]} from the
    archive, skipping macOS metadata noise."""
    buckets: dict[str, list[str]] = defaultdict(list)
    for n in zf.namelist():
        if not n.startswith(ROOT_DIR + '/'):
            continue
        if n.startswith('__MACOSX/'):
            continue
        parts = n.split('/')
        # parts[0] = 'GSL_openpose_data', parts[1] = sign name, parts[2] = file
        if len(parts) < 3 or not parts[1] or not parts[2]:
            continue
        if not parts[2].endswith('.json'):
            continue
        if parts[2].startswith('._'):  # mac metadata even outside __MACOSX
            continue
        buckets[parts[1]].append(n)
    for k in buckets:
        buckets[k].sort()
    return dict(buckets)


def _import_one(zf, sign_name: str, frame_paths: list[str], *,
                language: Language, variety: Variety, source: Source,
                fps: int) -> tuple[Sign, int, int]:
    """Returns (sign, n_frames_kept, n_frames_skipped)."""
    lemma, _ = Lemma.objects.get_or_create(gloss=sign_name)
    sign, _ = Sign.objects.update_or_create(
        lemma=lemma, variety=variety,
        defaults={'source': source, 'fps': fps,
                  'notes': f'Imported from GSL_openpose_data/{sign_name}/'})
    sign.frames.all().delete()

    duration_ms = max(1, int(round(1000 / fps)))
    rows = []
    n_skipped = 0
    for i, p in enumerate(frame_paths):
        try:
            data = json.loads(zf.read(p).decode('utf-8'))
            l_xyz, _, r_xyz, _ = openpose.parse_openpose_frame(data)
        except (ValueError, KeyError, UnicodeDecodeError):
            n_skipped += 1
            continue
        rotations = openpose.retarget_hands(l_xyz, r_xyz)
        rows.append(Frame(
            sign=sign,
            index=i,
            duration_ms=duration_ms,
            cylinder_rotations=rotations,
            openpose_joints={'left': l_xyz.tolist(),
                             'right': r_xyz.tolist()},
        ))
    Frame.objects.bulk_create(rows, batch_size=200)
    return sign, len(rows), n_skipped


class Command(BaseCommand):
    help = 'Stream-import the Ghanaian Sign Language Lexicon from a Zenodo zip.'

    def add_arguments(self, parser):
        parser.add_argument('zip_path',
                            help='Path to GSL_openpose_data.zip')
        parser.add_argument('--language',
                            default='Ghanaian Sign Language',
                            help='Language.name (created if missing).')
        parser.add_argument('--language-iso', default='gse',
                            help='ISO 639-3 code for the language.')
        parser.add_argument('--variety', default='gsl-lexicon-2021',
                            help='Variety.name within the language.')
        parser.add_argument('--limit', type=int, default=0,
                            help='Import at most N signs (0 = no cap).')
        parser.add_argument('--fps', type=int, default=30,
                            help='Frames-per-second to assume (default 30).')
        parser.add_argument('--start-at', default=None,
                            help='Skip signs lexicographically earlier than this name.')

    def handle(self, *args, **opts):
        zip_path = Path(opts['zip_path']).expanduser().resolve()
        if not zip_path.is_file():
            raise CommandError(f'zip not found: {zip_path}')

        # SQLite contention defence. The default journal mode
        # serialises every writer; Velour's identity_cron and
        # poll_inbox loops then collide with this bulk insert. WAL
        # mode lets a writer run while readers / brief other
        # writers proceed against the snapshot; busy_timeout adds
        # an explicit wait window for the rare WAL contention case.
        # journal_mode is *persistent* across connections once set
        # — fine to leave on for the rest of the project.
        with connection.cursor() as c:
            c.execute('PRAGMA journal_mode = WAL')
            c.execute('PRAGMA busy_timeout = 60000')

        lang, _ = Language.objects.update_or_create(
            name=opts['language'],
            defaults={'iso639_3': opts['language_iso'],
                      'region': 'Ghana',
                      'family': 'Adamorobe-affiliated; cf. ASL influence'})
        variety, _ = Variety.objects.update_or_create(
            language=lang, name=opts['variety'],
            defaults={'notes': 'Fragkiadakis–Nyst–Nyarko 2021 lexicon dump.'})
        source, _ = Source.objects.update_or_create(
            slug='zenodo-4533753',
            defaults={
                'name': 'Ghanaian Sign Language Lexicon (Zenodo 4533753)',
                'doi': '10.5281/zenodo.4533753',
                'url': 'https://zenodo.org/records/4533753',
                'license_text': 'CC-BY-4.0',
                'citation': ('Fragkiadakis, M., Nyst, V., & Nyarko, M. '
                             '(2021). Ghanaian Sign Language Lexicon. '
                             'Zenodo. doi:10.5281/zenodo.4533753.'),
            })

        self.stdout.write(self.style.NOTICE(
            f'opening {zip_path} (this enumerates a 270k-entry archive — '
            f'first scan takes a few seconds) ...'))
        t0 = time.monotonic()
        with zipfile.ZipFile(zip_path) as zf:
            buckets = _signs_in_zip(zf)
            sign_names = sorted(buckets.keys())
            if opts['start_at']:
                sign_names = [n for n in sign_names if n >= opts['start_at']]
            if opts['limit']:
                sign_names = sign_names[:opts['limit']]
            self.stdout.write(f'  scan took {time.monotonic() - t0:.1f}s; '
                              f'{len(sign_names)} signs queued for import')

            n_signs = 0
            n_frames = 0
            n_skipped = 0
            t_loop = time.monotonic()
            for name in sign_names:
                frame_paths = buckets[name]
                with transaction.atomic():
                    sign, kept, skipped = _import_one(
                        zf, name, frame_paths,
                        language=lang, variety=variety,
                        source=source, fps=opts['fps'])
                n_signs  += 1
                n_frames += kept
                n_skipped += skipped
                if n_signs % 50 == 0 or n_signs == len(sign_names):
                    elapsed = time.monotonic() - t_loop
                    rate = n_signs / elapsed if elapsed else 0
                    self.stdout.write(
                        f'  [{n_signs:4d}/{len(sign_names)}] {name:30s} '
                        f'{kept:4d} frames · {rate:.1f} signs/s')

        self.stdout.write(self.style.SUCCESS(
            f'\nimported {n_signs} signs · {n_frames} frames '
            f'(skipped {n_skipped} malformed) in '
            f'{time.monotonic() - t0:.1f}s'))
        self.stdout.write(f'  variety: {variety}')
        self.stdout.write(f'  sample : /signs/view/{Sign.objects.filter(variety=variety).first().slug}/')

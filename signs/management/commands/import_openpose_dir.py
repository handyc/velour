"""Import a directory of OpenPose JSON frames into the corpus.

Two import shapes:

  1. **Single sign** — the input directory contains a sequence of
     OpenPose JSON files (one per frame, lexicographic order). All
     frames go into one Sign.

  2. **Multi-sign root** — the input directory contains N
     subdirectories, each one a sign. Subdirectory names become
     the lemma glosses.

The retargeting is done in-process via signs.openpose. Raw
OpenPose joints are also stored alongside the derived cylinder
rotations so the data is roundtrippable.

Usage examples:
  manage.py import_openpose_dir /path/to/sign_water/ \\
      --language "Ghanaian Sign Language" --variety gsl-lexicon-2021 \\
      --lemma WATER
  manage.py import_openpose_dir /path/to/gsl_lexicon_root/ --multi \\
      --language "Ghanaian Sign Language" --variety gsl-lexicon-2021
"""

from __future__ import annotations
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from signs.models import Language, Variety, Lemma, Sign, Frame, Source
from signs import openpose


def _iter_openpose_files(d: Path):
    """Yield JSON files in d (lexicographic order). Filters to
    `*.json` to skip stray sidecar files (video, csv, README).
    """
    return sorted(d.glob('*.json'))


def _import_one_sign(*, sign_dir: Path, lemma_text: str, language: Language,
                     variety: Variety, source: Source | None, fps: int) -> Sign:
    lemma, _ = Lemma.objects.get_or_create(gloss=lemma_text)
    sign, _ = Sign.objects.update_or_create(
        lemma=lemma, variety=variety,
        defaults={'source': source, 'fps': fps,
                  'notes': f'Imported from {sign_dir.name}'})
    sign.frames.all().delete()

    frame_paths = _iter_openpose_files(sign_dir)
    if not frame_paths:
        return sign

    duration_ms = max(1, int(round(1000 / fps)))
    for i, fp in enumerate(frame_paths):
        with open(fp) as f:
            data = json.load(f)
        try:
            l_xyz, _l_c, r_xyz, _r_c = openpose.parse_openpose_frame(data)
        except (ValueError, KeyError):
            continue  # skip malformed/empty frames

        rotations = openpose.retarget_hands(l_xyz, r_xyz)
        Frame.objects.create(
            sign=sign,
            index=i,
            duration_ms=duration_ms,
            cylinder_rotations=rotations,
            openpose_joints={'left': l_xyz.tolist(),
                             'right': r_xyz.tolist()},
        )
    return sign


class Command(BaseCommand):
    help = 'Import OpenPose JSON frames as Sign(s) in the corpus.'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Directory of JSON frames (single sign) '
                                          'or directory of per-sign subdirs (with --multi).')
        parser.add_argument('--language', required=True,
                            help='Language.name; created if missing.')
        parser.add_argument('--variety', required=True,
                            help='Variety.name within the language; created if missing.')
        parser.add_argument('--lemma', default=None,
                            help='Lemma gloss for single-sign mode. Required without --multi.')
        parser.add_argument('--multi', action='store_true',
                            help='Treat `path` as a root of per-sign subdirectories; '
                                 'subdir names become lemma glosses.')
        parser.add_argument('--source-name', default=None,
                            help='Optional Source.name for citation metadata.')
        parser.add_argument('--source-doi', default='', help='Optional DOI.')
        parser.add_argument('--source-url', default='', help='Optional URL.')
        parser.add_argument('--license', default='', help='Optional license text.')
        parser.add_argument('--fps', type=int, default=30,
                            help='Frames per second to assume; default 30.')
        parser.add_argument('--limit', type=int, default=0,
                            help='In --multi mode, cap the number of signs '
                                 'imported (useful for sampling). 0 = no cap.')

    def handle(self, *args, **opts):
        path = Path(opts['path']).expanduser().resolve()
        if not path.is_dir():
            raise CommandError(f'not a directory: {path}')

        lang, _ = Language.objects.get_or_create(name=opts['language'])
        variety, _ = Variety.objects.get_or_create(
            language=lang, name=opts['variety'])

        source = None
        if opts['source_name']:
            source, _ = Source.objects.get_or_create(
                name=opts['source_name'],
                defaults={'doi': opts['source_doi'],
                          'url': opts['source_url'],
                          'license_text': opts['license']})

        if not opts['multi']:
            if not opts['lemma']:
                raise CommandError('--lemma is required without --multi')
            sign = _import_one_sign(
                sign_dir=path, lemma_text=opts['lemma'],
                language=lang, variety=variety, source=source,
                fps=opts['fps'])
            self.stdout.write(self.style.SUCCESS(
                f'imported {sign.lemma.gloss} [{variety.name}] '
                f'with {sign.n_frames} frames → /signs/view/{sign.slug}/'))
            return

        # Multi-sign mode.
        sign_dirs = sorted(d for d in path.iterdir() if d.is_dir())
        if opts['limit']:
            sign_dirs = sign_dirs[:opts['limit']]
        n_signs = 0
        n_frames_total = 0
        for d in sign_dirs:
            lemma_text = d.name.upper().replace('-', '_').replace(' ', '_')
            sign = _import_one_sign(
                sign_dir=d, lemma_text=lemma_text,
                language=lang, variety=variety, source=source,
                fps=opts['fps'])
            n_signs += 1
            n_frames_total += sign.n_frames
            self.stdout.write(
                f'  [{n_signs:4d}] {lemma_text:30s} {sign.n_frames:4d} frames')
        self.stdout.write(self.style.SUCCESS(
            f'imported {n_signs} signs ({n_frames_total} frames total) '
            f'into {variety}'))

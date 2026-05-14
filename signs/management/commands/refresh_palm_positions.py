"""Compute per-frame palm offsets for an already-imported corpus
by re-reading the original OpenPose zip.

Phase 1c only retargeted the hand keypoints — every Frame's
``palm_l_pos`` / ``palm_r_pos`` came out empty, so the viewer
renders all hands at the static rest position no matter where the
signer's hands actually moved. This command reads the body
keypoints (BODY_25's neck + shoulders + wrists) from each frame's
JSON, computes a body-normalised palm offset, and writes the
result to the existing Frame rows in place.

  manage.py refresh_palm_positions \\
      signs/imports/GSL_openpose_data.zip \\
      --variety gsl-lexicon-2021 [--scale 1.5] [--mirror-x]
"""

from __future__ import annotations
import json
import time
import zipfile
from pathlib import Path

import numpy as np

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from signs.models import Variety, Sign, Frame
from signs import openpose


ROOT_DIR = 'GSL_openpose_data'


def _frame_paths_for_sign(zf, sign_name: str):
    return sorted(
        n for n in zf.namelist()
        if n.startswith(f'{ROOT_DIR}/{sign_name}/')
        and n.endswith('.json')
        and not n.split('/')[-1].startswith('._')
    )


_CONF_THRESHOLD = 0.1   # OpenPose confidence below this = "undetected"


def _compute_offsets_for_sign(zf, sign_name: str, *,
                               scale: float, mirror_x: bool):
    """Walk a sign's per-frame JSONs and return a list of
    ``(palm_l, palm_r)`` per frame.

    Reference wrist positions are picked per hand from the first
    frame where that hand's wrist confidence exceeds
    ``_CONF_THRESHOLD``. If a hand is never detected, its offsets
    stay empty (the viewer falls back to its default rest position
    for that hand). Shoulder distance for normalisation comes from
    the first frame with a valid body keypoint set.
    """
    paths = _frame_paths_for_sign(zf, sign_name)
    if not paths:
        return [], 0

    # First pass: walk frames once, capturing per-hand reference
    # wrists (first detected) and the body's shoulder distance
    # (from the first valid body frame).
    ref_l = None
    ref_r = None
    ref_shoulder = None
    parsed: list[tuple] = []  # (l_xyz, l_conf, r_xyz, r_conf)
    for p in paths:
        try:
            data = json.loads(zf.read(p).decode())
            l_xyz, l_conf, r_xyz, r_conf = openpose.parse_openpose_frame(data)
            body = openpose.parse_openpose_body(data)
        except (ValueError, KeyError):
            parsed.append(None)
            continue
        parsed.append((l_xyz, l_conf, r_xyz, r_conf))
        if ref_shoulder is None:
            _, dist = openpose.body_frame(body)
            if dist > 0:
                ref_shoulder = dist
        if ref_l is None and l_conf[0] > _CONF_THRESHOLD:
            ref_l = l_xyz[0]
        if ref_r is None and r_conf[0] > _CONF_THRESHOLD:
            ref_r = r_xyz[0]

    if ref_shoulder is None or ref_shoulder <= 0:
        return [], 0

    # Second pass: per-frame offsets. A hand that's undetected in a
    # frame gets [] (viewer renders that hand at its rest position).
    out = []
    for entry in parsed:
        if entry is None:
            out.append(([], []))
            continue
        l_xyz, l_conf, r_xyz, r_conf = entry
        palm_l = (openpose.palm_offset(l_xyz[0], ref_l, ref_shoulder,
                                       scale=scale, mirror_x=mirror_x)
                  if ref_l is not None and l_conf[0] > _CONF_THRESHOLD
                  else [])
        palm_r = (openpose.palm_offset(r_xyz[0], ref_r, ref_shoulder,
                                       scale=scale, mirror_x=mirror_x)
                  if ref_r is not None and r_conf[0] > _CONF_THRESHOLD
                  else [])
        out.append((palm_l, palm_r))
    return out, len(out)


class Command(BaseCommand):
    help = ('Compute per-frame palm offsets from OpenPose body+wrist '
            'data and update existing Frame rows in place.')

    def add_arguments(self, parser):
        parser.add_argument('zip_path', help='Path to GSL_openpose_data.zip.')
        parser.add_argument('--variety', default='gsl-lexicon-2021',
                            help='Variety.name to refresh.')
        parser.add_argument('--scale', type=float, default=1.5,
                            help='Multiplier on the normalised wrist '
                                 'displacement (default 1.5).')
        parser.add_argument('--mirror-x', action='store_true',
                            help='Negate the x component (signer-perspective '
                                 'vs camera-perspective).')
        parser.add_argument('--limit', type=int, default=0,
                            help='Cap the number of signs refreshed.')

    def handle(self, *args, **opts):
        zip_path = Path(opts['zip_path']).expanduser().resolve()
        if not zip_path.is_file():
            raise CommandError(f'zip not found: {zip_path}')

        variety = Variety.objects.filter(name=opts['variety']).first()
        if not variety:
            raise CommandError(f'no variety named {opts["variety"]!r}')

        with connection.cursor() as c:
            c.execute('PRAGMA journal_mode = WAL')
            c.execute('PRAGMA busy_timeout = 60000')

        signs = list(Sign.objects.filter(variety=variety)
                                 .select_related('lemma')
                                 .order_by('lemma__gloss'))
        if opts['limit']:
            signs = signs[:opts['limit']]

        self.stdout.write(self.style.NOTICE(
            f'refreshing palm offsets for {len(signs)} signs '
            f'in {variety} (scale={opts["scale"]}, mirror_x={opts["mirror_x"]})'))

        t0 = time.monotonic()
        n_signs_done = 0
        n_frames_done = 0
        n_signs_skipped = 0

        with zipfile.ZipFile(zip_path) as zf:
            for sign in signs:
                offsets, _ = _compute_offsets_for_sign(
                    zf, sign.lemma.gloss,
                    scale=opts['scale'],
                    mirror_x=opts['mirror_x'])
                if not offsets:
                    n_signs_skipped += 1
                    continue

                # Pair offsets with existing Frame rows by index order.
                frames = list(sign.frames.order_by('index'))
                pairs = list(zip(frames, offsets))
                for frame, (pl, pr) in pairs:
                    frame.palm_l_pos = pl
                    frame.palm_r_pos = pr

                with transaction.atomic():
                    Frame.objects.bulk_update(
                        [fr for fr, _ in pairs],
                        ['palm_l_pos', 'palm_r_pos'],
                        batch_size=200)

                n_signs_done += 1
                n_frames_done += len(pairs)
                if n_signs_done % 50 == 0:
                    elapsed = time.monotonic() - t0
                    self.stdout.write(
                        f'  [{n_signs_done:4d}/{len(signs)}] {sign.lemma.gloss:30s} '
                        f'{len(pairs):4d} frames · {n_signs_done/elapsed:.1f} signs/s')

        elapsed = time.monotonic() - t0
        self.stdout.write(self.style.SUCCESS(
            f'\nrefreshed {n_signs_done} signs · {n_frames_done} frames '
            f'(skipped {n_signs_skipped}) in {elapsed:.1f}s'))

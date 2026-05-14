"""Seed a small demo corpus so the in-Velour viewer has something
to play before any real lexicon import.

Creates:
- Language 'Test (signtest demo)'
- Variety 'signtest-demo'
- Lemmas + Signs for REST, FIST, POINT, WAVE
- Each Sign has 1-8 hand-coded frames

Idempotent: re-running updates the existing rows in place.
"""

from __future__ import annotations
import math

from django.core.management.base import BaseCommand

from signs.models import Language, Variety, Lemma, Sign, Frame, Source


def _flat_pose(values_per_finger):
    """Build a 30-element pose from a (10, 3)-shape iterable.

    Order: L_Thumb, L_Index, L_Middle, L_Ring, L_Pinky,
           R_Thumb, R_Index, R_Middle, R_Ring, R_Pinky;
    each entry is [seg0_bend, seg1_bend, seg2_bend] in radians
    on rx (flexion). ry, rz default to 0.
    """
    pose = []
    for finger_bends in values_per_finger:
        for bend in finger_bends:
            pose.append([float(bend), 0.0, 0.0])
    return pose


def _pose_rest():
    """30 × [0, 0, 0]."""
    return _flat_pose([[0.0]*3 for _ in range(10)])


def _pose_fist():
    """All fingers curled ~90°; thumb folds 30°."""
    THUMB_CURL = 0.5
    FINGER_CURL = math.pi / 2
    return _flat_pose([
        [THUMB_CURL, THUMB_CURL, THUMB_CURL],         # L thumb
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # L index
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # L middle
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # L ring
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # L pinky
        [THUMB_CURL, THUMB_CURL, THUMB_CURL],         # R thumb
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # R index
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # R middle
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # R ring
        [FINGER_CURL, FINGER_CURL, FINGER_CURL],      # R pinky
    ])


def _pose_point():
    """Both hands point forward: index extended, other fingers curled."""
    THUMB_CURL = 0.4
    CURL = math.pi / 2
    EXTENDED = [0.0, 0.0, 0.0]
    return _flat_pose([
        [THUMB_CURL, THUMB_CURL, THUMB_CURL],   # L thumb
        EXTENDED,                                # L index extended
        [CURL, CURL, CURL],                      # L middle
        [CURL, CURL, CURL],                      # L ring
        [CURL, CURL, CURL],                      # L pinky
        [THUMB_CURL, THUMB_CURL, THUMB_CURL],   # R thumb
        EXTENDED,                                # R index extended
        [CURL, CURL, CURL],                      # R middle
        [CURL, CURL, CURL],                      # R ring
        [CURL, CURL, CURL],                      # R pinky
    ])


def _wave_frames(n=8):
    """Open-hand wave: palm_r position oscillates side-to-side.
    Fingers stay extended; right wrist would normally tilt — for
    the demo we just translate the right palm laterally."""
    rest = _pose_rest()
    frames = []
    for i in range(n):
        t = i / (n - 1)
        # Wave: x oscillates +/- 0.4 over the cycle
        x = 0.4 * math.sin(2 * math.pi * t)
        frames.append({
            'index': i,
            'duration_ms': 80,
            'cylinder_rotations': rest,
            'palm_r_pos': [x, 0.0, 0.0],
        })
    return frames


def _upsert_sign(lemma, variety, source, frames):
    sign, _ = Sign.objects.update_or_create(
        lemma=lemma, variety=variety,
        defaults={'source': source, 'fps': 12,
                  'notes': 'Hand-coded demo for Phase 1a smoke test.'},
    )
    sign.frames.all().delete()  # idempotent re-seed
    for f in frames:
        Frame.objects.create(
            sign=sign,
            index=f['index'],
            duration_ms=f.get('duration_ms', 100),
            cylinder_rotations=f['cylinder_rotations'],
            wrist_l_rot=f.get('wrist_l_rot', []),
            wrist_r_rot=f.get('wrist_r_rot', []),
            palm_l_pos=f.get('palm_l_pos', []),
            palm_r_pos=f.get('palm_r_pos', []),
            openpose_joints=[],
        )
    return sign


class Command(BaseCommand):
    help = 'Seed a small hand-coded demo corpus (REST, FIST, POINT, WAVE).'

    def handle(self, *args, **opts):
        lang, _ = Language.objects.update_or_create(
            name='Test (signtest demo)',
            defaults={'region': 'n/a', 'family': 'n/a',
                      'notes': 'Synthetic demo poses for testing the viewer.'},
        )
        variety, _ = Variety.objects.update_or_create(
            language=lang, name='signtest-demo',
            defaults={'notes': 'Hand-coded demo set; not a real signed language.'},
        )
        source, _ = Source.objects.update_or_create(
            name='signtest.games.h4ks.com demo set',
            defaults={'license_text': 'demo / synthetic',
                      'url': 'https://signtest.games.h4ks.com/'},
        )

        rest_lemma,  _ = Lemma.objects.update_or_create(gloss='REST',  defaults={'semantic_field': 'meta'})
        fist_lemma,  _ = Lemma.objects.update_or_create(gloss='FIST',  defaults={'semantic_field': 'handshape'})
        point_lemma, _ = Lemma.objects.update_or_create(gloss='POINT', defaults={'semantic_field': 'handshape'})
        wave_lemma,  _ = Lemma.objects.update_or_create(gloss='WAVE',  defaults={'semantic_field': 'greeting'})

        _upsert_sign(rest_lemma,  variety, source,
                     [{'index': 0, 'duration_ms': 500,
                       'cylinder_rotations': _pose_rest()}])
        _upsert_sign(fist_lemma,  variety, source,
                     [{'index': 0, 'duration_ms': 500,
                       'cylinder_rotations': _pose_fist()}])
        _upsert_sign(point_lemma, variety, source,
                     [{'index': 0, 'duration_ms': 500,
                       'cylinder_rotations': _pose_point()}])
        _upsert_sign(wave_lemma,  variety, source, _wave_frames(8))

        self.stdout.write(self.style.SUCCESS(
            f'seeded {Sign.objects.filter(variety=variety).count()} demo signs '
            f'under language={lang.name!r}, variety={variety.name!r}'))
        for s in Sign.objects.filter(variety=variety).order_by('lemma__gloss'):
            self.stdout.write(f'  /signs/view/{s.slug}/  ({s.n_frames} frames)')

"""Sign-language corpus: language → variety → lemma → sign → frame.

A *Sign* is one (lemma, variety) pair of frames. Each frame stores
two parallel views of the pose:

- ``openpose_joints``: the raw 3D keypoint positions for the upper
  body and both hands as OpenPose emits them. 95-ish (x, y, z)
  tuples per frame. Lossless; kept for retargeting, comparison,
  and provenance audits.
- ``cylinder_rotations``: a 30-element list of local Euler
  ``[rx, ry, rz]`` (radians) matching the 30-cylinder hierarchy
  that the in-Velour viewer renders directly. Derived from the
  joint positions via inverse kinematics on the hand skeleton.

Plus per-frame wrist and palm transforms so the hands actually
move through space across a sign (the 30 cylinder rotations alone
are silent on global position).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.text import slugify


class Language(models.Model):
    """A signed language. Distinct from Variety: a language can
    have several signing forms under it (cf. Ghanaian SL → ENGLISH,
    BROKEN, LOCAL)."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    # ISO 639-3 has codes for several signed languages (e.g. gse
    # for Ghanaian SL); leave blank where no code exists.
    iso639_3 = models.CharField(max_length=8, blank=True)

    region = models.CharField(max_length=120, blank=True,
        help_text='Geographic region or country.')
    family = models.CharField(max_length=120, blank=True,
        help_text='Linguistic family or genealogy, where known.')
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.name)[:120] or 'lang'
        super().save(*a, **kw)


class Variety(models.Model):
    """A sub-form within a Language. Names like 'gsl-english',
    'gsl-broken', 'gsl-local' for Ghanaian SL, or
    'adamorobe-sl' for the village SL of Adamorobe."""

    language = models.ForeignKey(Language, on_delete=models.CASCADE,
                                 related_name='varieties')
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['language__name', 'name']
        constraints = [
            models.UniqueConstraint(fields=['language', 'name'],
                                    name='unique_variety_per_language'),
        ]

    def __str__(self):
        return f'{self.language.name} / {self.name}'

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(f'{self.language.name}-{self.name}')[:120] or 'var'
            self.slug = base
            i = 2
            while type(self).objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                tail = f'-{i}'
                self.slug = base[:120 - len(tail)] + tail
                i += 1
        super().save(*a, **kw)


class Lemma(models.Model):
    """A gloss — the meaning a Sign carries. Cross-variety: the
    lemma 'WATER' may have distinct Signs in GSL and in
    Adamorobe SL, but the Lemma row is shared so comparisons can
    be lined up."""

    gloss = models.CharField(max_length=120, unique=True,
        help_text='Conventional all-caps gloss, e.g. "WATER", "HELLO".')
    slug = models.SlugField(max_length=120, unique=True)
    semantic_field = models.CharField(max_length=80, blank=True,
        help_text='Coarse semantic bucket (greeting, kinship, food, ...).')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['gloss']

    def __str__(self):
        return self.gloss

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.gloss)[:120] or 'lemma'
        super().save(*a, **kw)


class Source(models.Model):
    """Citation metadata for a corpus or single recording."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    citation = models.TextField(blank=True,
        help_text='Full bibliographic citation.')
    url = models.URLField(blank=True)
    doi = models.CharField(max_length=80, blank=True)
    license_text = models.CharField(max_length=120, blank=True,
        help_text='e.g. CC-BY-4.0, CC0, all-rights-reserved.')
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = slugify(self.name)[:200] or 'source'
        super().save(*a, **kw)


class Sign(models.Model):
    """One (lemma × variety) realization. Multiple Signs per
    (lemma, variety) are allowed — different recordings, different
    signers, different dialect-internal alternants."""

    lemma = models.ForeignKey(Lemma, on_delete=models.CASCADE,
                              related_name='signs')
    variety = models.ForeignKey(Variety, on_delete=models.CASCADE,
                                related_name='signs')
    slug = models.SlugField(max_length=200, unique=True)

    signer = models.CharField(max_length=120, blank=True,
        help_text='Identifier of the signer; can be a name or '
                  'anonymised code.')
    recorded_at = models.DateField(null=True, blank=True)

    source = models.ForeignKey(Source, on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name='signs')

    media_url = models.URLField(blank=True,
        help_text='Optional video URL of the original recording.')

    notes = models.TextField(blank=True)
    fps = models.PositiveSmallIntegerField(default=30,
        help_text='Frames per second the recording was sampled at.')

    # Fixed-size signature used by the similarity engine: a list of
    # K_SIGNATURE_KEYFRAMES evenly-spaced frame poses, each flattened
    # to 90 floats (30 cylinders × [rx, ry, rz]), then L2-normalised
    # across the whole vector. Stored so /signs/<slug>/similar/ can
    # rank 1200 candidates without loading every frame. NULL until
    # the importer or `manage.py compute_sign_signatures` populates it.
    signature = models.JSONField(null=True, blank=True,
        help_text='K_SIGNATURE_KEYFRAMES × 90-float pose signature, '
                  'L2-normalised. Recomputed whenever frames change.')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                   on_delete=models.SET_NULL,
                                   null=True, blank=True,
                                   related_name='signs')

    class Meta:
        ordering = ['lemma__gloss', 'variety__name']

    def __str__(self):
        return f'{self.lemma.gloss} [{self.variety.name}]'

    def save(self, *a, **kw):
        if not self.slug:
            self.slug = self.derive_slug()
        super().save(*a, **kw)

    def derive_slug(self) -> str:
        """``<lemma>-<variety-name>`` slugified, with a numeric tail
        on collision. Variety's *name* (not slug) is used because
        the variety slug already contains the language name and
        would yield duplicated segments like
        ``water-ghanaian-sign-language-gsl-lexicon-2021``."""
        base = slugify(f'{self.lemma.gloss}-{self.variety.name}')[:200] or 'sign'
        slug = base
        i = 2
        while type(self).objects.filter(slug=slug).exclude(pk=self.pk).exists():
            tail = f'-{i}'
            slug = base[:200 - len(tail)] + tail
            i += 1
        return slug

    @property
    def n_frames(self) -> int:
        return self.frames.count()

    def recompute_signature(self) -> list:
        """Recompute and persist the pose signature from the current
        frames. Includes per-frame palm offsets when they're
        populated. Importers call this after bulk-creating Frame
        rows. Returns the signature list."""
        from .similarity import compute_signature
        frame_data = list(self.frames.order_by('index').values_list(
            'cylinder_rotations', 'palm_l_pos', 'palm_r_pos'))
        rotations = [r for r, _, _ in frame_data]
        palm_l    = [pl for _, pl, _ in frame_data]
        palm_r    = [pr for _, _, pr in frame_data]
        self.signature = compute_signature(rotations, palm_l, palm_r)
        Sign.objects.filter(pk=self.pk).update(signature=self.signature)
        return self.signature


class Frame(models.Model):
    """One frame of a Sign.

    Two parallel pose representations are stored side by side so
    importers can roundtrip raw data without lossy conversion AND
    the renderer can play immediately without recomputing IK:

    - ``openpose_joints``: list of (x, y, z) keypoint positions in
      OpenPose ordering. Empty for hand-keyed demo signs that have
      no OpenPose origin.
    - ``cylinder_rotations``: 30-element list of [rx, ry, rz] local
      Euler in radians, matching the signtest viewer's
      HAND_STRUCTURE order (L_Thumb_1..L_Pinky_3, then
      R_Thumb_1..R_Pinky_3).

    ``wrist_l_rot`` / ``wrist_r_rot`` / ``palm_l_pos`` / ``palm_r_pos``
    are kept separate from the 30 finger rotations so the renderer
    can place each hand in space without packing positional data
    into a rotation slot.
    """

    sign = models.ForeignKey(Sign, on_delete=models.CASCADE,
                             related_name='frames')
    index = models.PositiveIntegerField(help_text='0-based frame number.')
    duration_ms = models.PositiveSmallIntegerField(default=33,
        help_text='Display duration in ms; default is 1/30 s.')

    cylinder_rotations = models.JSONField(default=list,
        help_text='30 × [rx, ry, rz] local Euler radians.')

    wrist_l_rot = models.JSONField(default=list,
        help_text='[rx, ry, rz] left wrist rotation.')
    wrist_r_rot = models.JSONField(default=list,
        help_text='[rx, ry, rz] right wrist rotation.')
    palm_l_pos  = models.JSONField(default=list,
        help_text='[x, y, z] left palm position; empty = default.')
    palm_r_pos  = models.JSONField(default=list,
        help_text='[x, y, z] right palm position; empty = default.')

    openpose_joints = models.JSONField(default=list, blank=True,
        help_text='Raw OpenPose joint positions; empty when the '
                  'sign was hand-keyed rather than imported.')

    class Meta:
        ordering = ['sign__slug', 'index']
        constraints = [
            models.UniqueConstraint(fields=['sign', 'index'],
                                    name='unique_frame_per_sign'),
        ]

    def __str__(self):
        return f'{self.sign.slug}#{self.index}'

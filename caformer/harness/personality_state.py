"""PersonalityState: the canonical 4-tuple personality fingerprint.

Each axis has 4 K=4-aligned values, so the full state fits in
4 bytes (or 8 bits if packed tightly).  256 distinct compositions.

Axes:

  drive       — motivation / why this utterance exists
  expression  — rhetorical mode / how it sounds
  relation    — intimacy / who-to-whom register
  lens        — perception filter / which side of the message gets heard

The values per axis are pulled from established communication frameworks
shipped as 'axis'-kind PersonalityModule rows:

  drive       d'Ansembourg's Four Conversational Intentions
  expression  David Angel's Four Ds
  relation    Coaching levels
  lens        Schulz von Thun's Four Sides

PersonalityState.from_path((a, b, c, d)) treats a boardstack4 cascade
path directly as a state — same K=4 shape, no translation needed.
"""
from __future__ import annotations

from dataclasses import dataclass


AXES = ('drive', 'expression', 'relation', 'lens')


# Per-axis labels.  Used for debugging / display / handler output.
# Indexed 0..3.  Sourced from the canonical PersonalityModule rows
# at seed time and cached here for offline use.
AXIS_LABELS: dict[str, tuple[str, str, str, str]] = {
    'drive': (
        'discharge', 'inform', 'control', 'connect',
    ),
    'expression': (
        'dialogue', 'discourse', 'debate', 'diatribe',
    ),
    'relation': (
        'small-talk', 'fact-sharing', 'opinions', 'feelings',
    ),
    'lens': (
        'fact', 'self-revealing', 'relationship', 'appeal',
    ),
}


# Canonical source PersonalityModule slugs that DEFINE each axis.
AXIS_SOURCE_SLUGS: dict[str, str] = {
    'drive':      'dansembourg-intentions',
    'expression': 'david-angel',
    'relation':   'coaching',
    'lens':       'schulz-von-thun',
}


@dataclass(frozen=True)
class PersonalityState:
    """The four-axis personality fingerprint.

    Construct from a cascade path: PersonalityState.from_path((1,2,0,3)).
    Render compactly: str(state) → 'drv=inform·exp=debate·rel=small-talk·lens=appeal'."""
    drive:      int = 0
    expression: int = 0
    relation:   int = 0
    lens:       int = 0

    def __post_init__(self):
        # Clamp to K=4.  Frozen + dataclass means we go through
        # object.__setattr__.
        for f in AXES:
            v = int(getattr(self, f)) & 3
            object.__setattr__(self, f, v)

    @classmethod
    def from_path(cls, path) -> 'PersonalityState':
        """Treat a 4-tuple cascade path as a PersonalityState.  Shorter
        paths are zero-padded; longer paths are truncated."""
        if path is None:
            return cls()
        seq = list(path)[:4] + [0] * (4 - len(list(path)))
        return cls(drive=int(seq[0]) & 3,
                    expression=int(seq[1]) & 3,
                    relation=int(seq[2]) & 3,
                    lens=int(seq[3]) & 3)

    @classmethod
    def from_vector(cls, vec) -> 'PersonalityState':
        return cls.from_path(vec)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.drive, self.expression, self.relation, self.lens)

    def as_bytes(self) -> bytes:
        return bytes(self.as_tuple())

    def labels(self) -> dict[str, str]:
        return {
            'drive':      AXIS_LABELS['drive'][self.drive],
            'expression': AXIS_LABELS['expression'][self.expression],
            'relation':   AXIS_LABELS['relation'][self.relation],
            'lens':       AXIS_LABELS['lens'][self.lens],
        }

    def __str__(self) -> str:
        L = self.labels()
        return (f"drv={L['drive']}·exp={L['expression']}"
                f"·rel={L['relation']}·lens={L['lens']}")


# ─── Refresh axis labels from the DB if available ─────────────────


def refresh_labels_from_db() -> None:
    """Pull each axis's 4 labels from the corresponding axis-kind
    PersonalityModule row.  Called once at module load when the DB
    is available; subsequent prompts use the cached AXIS_LABELS dict."""
    try:
        from caformer.models import PersonalityModule
        for axis, slug in AXIS_SOURCE_SLUGS.items():
            m = PersonalityModule.objects.filter(slug=slug).first()
            if m and m.subroutes and len(m.subroutes) >= 4:
                AXIS_LABELS[axis] = tuple(
                    (m.subroutes[i].get('label') or AXIS_LABELS[axis][i])
                    .lower().replace(' ', '-')
                    for i in range(4))
    except Exception:                                # noqa: BLE001
        pass


# ─── Convenience: compute state for a prompt via boardstack4 ──────


def compute_state(prompt: str) -> PersonalityState:
    """Run the boardstack4 cascade on ``prompt``; treat its 4-tuple
    path as a PersonalityState.  Soft-fails to the zero state."""
    try:
        from caformer import boardstack4 as _bs4
        stack = _bs4.get_stack()
        path = stack.cascade(prompt)
        return PersonalityState.from_path(path)
    except Exception:                                # noqa: BLE001
        return PersonalityState()


def preset_for_module(slug: str) -> PersonalityState | None:
    """Look up a named preset (kind='preset' PersonalityModule)."""
    try:
        from caformer.models import PersonalityModule
        m = PersonalityModule.objects.filter(
            slug=slug, kind='preset').first()
        if m and m.state_vector and len(m.state_vector) >= 4:
            return PersonalityState.from_path(m.state_vector)
    except Exception:                                # noqa: BLE001
        pass
    return None

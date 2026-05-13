"""spoeqi — Shared-state CA pacts.

A Pact is a pre-shared seed packet plus a 4-colour hex CA rule.  Two
parties holding identical Pacts and starting their CAs at the same
event will see identical output forever — not because anything is
transmitted, but because deterministic computation from the same
seed produces the same result.

Information-theoretically, no new data crosses between parties; the
"transmission" is a stand-in for entanglement-style shared randomness.
The real value is *shared computational state*: a substrate both
sides can extract a keystream from, feed into perturbation layers
over an identical pre-trained model, etc.

Phase 1 (this file): the Pact substrate and the 64-component CA grid.
Phase 2+ (deferred): keystream extraction → LoRA perturbation → MoE
gate routing — see Codex Manual `spoeqi-vision`.
"""

from __future__ import annotations
import os
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


# Components in the multi-CA = 64 (the 8×8 seed matrix).
COMPONENTS = 64

# Per-component hex grid side length.  Default 16×16; the Pact may
# override per-instance.  Total visible cells = COMPONENTS × side².
COMPONENT_GRID = 16
COMPONENT_GRID_CHOICES = [
    ( 8, ' 8 × 8  (tiny, 4,096 cells total)'),
    (16, '16 × 16 (default, 16,384 cells)'),
    (24, '24 × 24 (36,864 cells)'),
    (32, '32 × 32 (65,536 cells)'),
    (48, '48 × 48 (147,456 cells)'),
    (64, '64 × 64 (262,144 cells; cells render as pixels)'),
]

# 4 self-states × 4^6 neighbour configurations = 16,384 entries.
RULE_TABLE_SIZE = 16384


def _random_rule() -> bytes:
    """Deterministically *random* rule: each of 16,384 entries is a
    uniform draw from {0,1,2,3}.  Not edge-of-chaos; useful as a
    placeholder when no Tessera-baked rule is on hand.  Wraps
    `secrets.token_bytes` so the rule itself isn't reproducible (the
    *Pact* is reproducible — the rule is fixed at creation).
    """
    raw = secrets.token_bytes(RULE_TABLE_SIZE)
    return bytes(b & 0x03 for b in raw)


def _identity_rule() -> bytes:
    """The trivial 'cell stays the same' rule — every entry returns
    the self-state bits.  Useful for sanity-checking the JS engine
    (every CA should freeze immediately) before swapping in a
    behavioural rule."""
    out = bytearray(RULE_TABLE_SIZE)
    for key in range(RULE_TABLE_SIZE):
        out[key] = (key >> 12) & 0x03
    return bytes(out)


DEFAULT_PALETTE = [
    [220,  80,  40],   # 0  warm vermilion
    [ 60, 120, 210],   # 1  cool azure
    [ 80, 180,  90],   # 2  verdant
    [230, 200,  60],   # 3  amber
]


def random_palette(rng=None):
    """Four distinct, visually-separated colours.  4 hues evenly spaced
    on the wheel with a random rotation, saturation in [0.55, 0.95],
    value in [0.55, 0.95].  HSV picks beat uniform RGB picks — the
    latter produces frequent muddy / low-contrast combinations."""
    import random as _r
    import colorsys
    if rng is None:
        rng = _r.SystemRandom()
    rotation = rng.random()
    palette = []
    for i in range(4):
        h = (rotation + i / 4 + rng.uniform(-0.03, 0.03)) % 1.0
        s = rng.uniform(0.55, 0.95)
        v = rng.uniform(0.55, 0.95)
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        palette.append([int(r * 255), int(g * 255), int(b * 255)])
    rng.shuffle(palette)
    return palette


def random_palette_per_component(rng=None):
    """A separate HSV palette for each of the 64 components.  Returned
    shape: list of 64 sub-palettes, each `[[r,g,b]×4]`.  Detected
    downstream by `isinstance(palette[0][0], list)` (single palettes
    have ints at that depth).
    """
    return [random_palette(rng=rng) for _ in range(COMPONENTS)]


def is_per_component_palette(palette) -> bool:
    """True iff the palette is shaped as 64 sub-palettes instead of 4
    flat colours.  Used by views + admin + the export pipeline."""
    return (isinstance(palette, list)
            and len(palette) == COMPONENTS
            and isinstance(palette[0], list)
            and palette[0]
            and isinstance(palette[0][0], list))


def compile_det_rule(rules_json) -> bytes:
    """Convert a Det `rules_json` list (sparse, with wildcards) into
    spoeqi's dense 16,384-byte 4-state lookup.

    Det format: ``[{'s': self_color, 'n': [n0..n5 with -1 wildcards],
    'r': result_color}, ...]``.  Rules apply in list order; first match
    wins.  Cells with no matching rule keep their self-state — the
    classic Automaton/Det convention.

    Spoeqi format: 16,384 bytes indexed by
    ``(self << 12) | (n0 << 10) | (n1 << 8) | (n2 << 6) | (n3 << 4) |
    (n4 << 2) | n5``, each byte in {0,1,2,3}.

    Identity default keeps unmatched 4-colour configurations stable so
    Det rules bred at n_colors=3 (which never produce a state-3 output)
    don't introduce gratuitous churn on any state-3 cells that survived
    seed expansion.
    """
    out = bytearray(RULE_TABLE_SIZE)
    for key in range(RULE_TABLE_SIZE):
        out[key] = (key >> 12) & 0x03
    for key in range(RULE_TABLE_SIZE):
        s = (key >> 12) & 0x03
        n0 = (key >> 10) & 0x03
        n1 = (key >> 8)  & 0x03
        n2 = (key >> 6)  & 0x03
        n3 = (key >> 4)  & 0x03
        n4 = (key >> 2)  & 0x03
        n5 = key         & 0x03
        for rule in rules_json:
            if rule['s'] != s:
                continue
            nb = rule['n']
            if ((nb[0] != -1 and nb[0] != n0) or
                (nb[1] != -1 and nb[1] != n1) or
                (nb[2] != -1 and nb[2] != n2) or
                (nb[3] != -1 and nb[3] != n3) or
                (nb[4] != -1 and nb[4] != n4) or
                (nb[5] != -1 and nb[5] != n5)):
                continue
            out[key] = rule['r'] & 0x03
            break
    return bytes(out)


class Pact(models.Model):
    """A shared-state contract between two parties.

    Identity-of-output guarantee: given an identical `seed_matrix`,
    `rule_snapshot`, `palette`, `clock_model`, and `launch_time`,
    two browsers anywhere will render the same 8×8 grid of CAs at
    the same logical tick.
    """

    CLOCK_CHOICES = [
        ('synced', 'synced — ticks from launch_time on UTC clock '
                   '(two viewers anywhere see identical state)'),
        ('local',  'local — ticks from page-load on viewer clock '
                   '(time dilation analogue; each viewer diverges)'),
    ]

    # Rule-diversity strategy controls whether all 64 components share
    # a single rule (cheap, but every component dynamic looks alike)
    # or each has its own rule (more entropy in the per-tick keystream
    # for Phase 2; more independent unforgeable surface — an attacker
    # who recovers one component-rule has cracked 1/64 of the state).
    DIVERSITY_CHOICES = [
        ('shared',  'shared — 1 rule × 64 seeds (current behaviour; '
                    'cheapest)'),
        ('mutated', 'mutated — 1 base rule + 64 deterministic perturbations '
                    '(rule diversity with shared lineage)'),
        ('fleet',   'fleet — 64 independent Hexhunt class-4 rules '
                    '(maximum diversity; ~1 MiB rule data)'),
    ]

    name        = models.CharField(max_length=80, unique=True)
    slug        = models.SlugField(max_length=80, unique=True)

    party_a     = models.CharField(max_length=40, default='Alice')
    party_b     = models.CharField(max_length=40, default='Bob')

    # 64 bytes — one PRNG seed byte per CA component.
    seed_matrix = models.BinaryField(
        help_text='64 bytes; one PRNG seed per component CA.')

    # Single 16,384-byte rule.  Always populated; broadcast to all 64
    # components when rule_diversity='shared'; serves as the base when
    # rule_diversity='mutated'; carries the first of 64 when 'fleet'
    # (so it's a sensible default if anything reads only this field).
    rule_snapshot = models.BinaryField(
        help_text='16384 bytes; one 4-state CA output per key.')

    rule_diversity = models.CharField(
        max_length=10, choices=DIVERSITY_CHOICES, default='shared',
        help_text='How rules are distributed across the 64 components.')

    # 1 MiB total when populated: 64 components × 16,384 bytes.  Null
    # when rule_diversity='shared'.  Layout is component-major
    # (concatenated rules in component order 0..63).
    rules_snapshot = models.BinaryField(
        null=True, blank=True,
        help_text='64 × 16384 = 1048576 bytes; per-component rules, '
                  'concatenated.  NULL when diversity=shared.')

    mutation_density = models.PositiveSmallIntegerField(
        default=1024,
        help_text='When diversity=mutated, number of rule-table entries '
                  'per component that get flipped from the base rule.  '
                  '1024 ≈ 6 %% of the 16,384-entry table.')

    # When diversity='fleet', the list of 64 Det Candidate IDs in
    # component order (component 0 → IDs[0], …, component 63 → IDs[63]).
    # NULL for other diversity modes.  Soft reference: the rule bytes
    # are already snapshotted into rules_snapshot, so the source rows
    # are safe to delete.
    fleet_candidate_ids = models.JSONField(
        null=True, blank=True, default=None,
        help_text='List of 64 Det Candidate IDs in component order. '
                  'NULL when diversity != fleet.')

    palette     = models.JSONField(
        default=list,
        help_text='Four [r,g,b] anchors for the four cell states.')

    clock_model = models.CharField(
        max_length=8, choices=CLOCK_CHOICES, default='synced')

    tick_ms     = models.PositiveIntegerField(
        default=180,
        help_text='Milliseconds per CA generation under synced clock; '
                  'also the default for local clock.')

    component_grid = models.PositiveSmallIntegerField(
        default=COMPONENT_GRID, choices=COMPONENT_GRID_CHOICES,
        help_text='Side length of each component CA in hex cells.')

    launch_time = models.DateTimeField(
        help_text='UTC moment the pact "engages".  For synced clock '
                  'this fixes the tick zero.  Earlier than now → '
                  'state is already advanced when first opened.')

    notes       = models.TextField(blank=True)

    # Soft provenance — which Det Candidate (if any) the rule was
    # compiled from.  on_delete=SET_NULL because rule_snapshot is a
    # full copy; the Pact remains playable even after Det is purged.
    det_candidate = models.ForeignKey(
        'det.Candidate', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='spoeqi_pacts',
        help_text='Optional source Hexhunt class-4 candidate.')

    created_at  = models.DateTimeField(auto_now_add=True)
    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='spoeqi_pacts')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *a, **kw):
        if not self.slug:
            base = slugify(self.name)[:80] or 'pact'
            self.slug = base
            i = 2
            while type(self).objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                tail = f'-{i}'
                self.slug = base[:80 - len(tail)] + tail
                i += 1
        if not self.seed_matrix:
            self.seed_matrix = secrets.token_bytes(COMPONENTS)
        if not self.rule_snapshot:
            self.rule_snapshot = _random_rule()
        if not self.palette:
            self.palette = [row[:] for row in DEFAULT_PALETTE]
        if not self.launch_time:
            self.launch_time = timezone.now()
        super().save(*a, **kw)

    @property
    def seed_hex(self) -> str:
        return bytes(self.seed_matrix).hex()

    @property
    def rule_hex(self) -> str:
        """Hex encoding of the full 16,384-byte rule.  Each byte
        holds one 4-state output; JS reconstructs by iterating."""
        return bytes(self.rule_snapshot).hex()

    def per_component_rules(self) -> bytes:
        """1 MiB of per-component rule bytes — 64 × 16,384.  For
        diversity='shared' we broadcast the single rule to all 64
        slots so the JS engine has a uniform code path."""
        if self.rule_diversity == 'shared' or not self.rules_snapshot:
            return bytes(self.rule_snapshot) * COMPONENTS
        return bytes(self.rules_snapshot)

    @property
    def rules_hex(self) -> str:
        """Hex encoding of the full 64 × 16384 rules.  ~2 MiB of hex
        text; embedded directly in the detail page payload."""
        return self.per_component_rules().hex()


def mutate_rule(base_rule: bytes, density: int, seed: int) -> bytes:
    """Flip `density` random entries of a 16,384-byte rule to a new
    random 4-state value.  Deterministic in (base, density, seed).
    The mutation can flip an entry to its current value (~25 % no-op)
    — that's fine; nominal density is "samples drawn, not changes
    guaranteed", consistent with how GA mutation operators count."""
    import random as _r
    rng = _r.Random(seed)
    out = bytearray(base_rule)
    n = len(out)
    for _ in range(density):
        idx = rng.randrange(n)
        out[idx] = rng.randrange(4)
    return bytes(out)


def synthesise_rules_fleet(candidate_ids):
    """Compile a list of Det Candidate IDs into 64 × 16384 bytes,
    concatenated in candidate-list order.  Raises ValueError if the
    list isn't exactly COMPONENTS long or any candidate isn't 4-color."""
    from det.models import Candidate
    if len(candidate_ids) != COMPONENTS:
        raise ValueError(
            f'Fleet needs exactly {COMPONENTS} candidates, got {len(candidate_ids)}.')
    cands = {c.id: c for c in
             Candidate.objects.filter(pk__in=candidate_ids).select_related('run')}
    out = bytearray()
    for cid in candidate_ids:
        c = cands.get(cid)
        if c is None:
            raise ValueError(f'Candidate #{cid} not found.')
        if c.run.n_colors != 4:
            raise ValueError(
                f'Candidate #{cid} has n_colors={c.run.n_colors} (need 4).')
        out += compile_det_rule(c.rules_json)
    return bytes(out)


def synthesise_rules_mutated(base_rule: bytes, density: int,
                              master_seed: int) -> bytes:
    """1 MiB output: 64 perturbations of `base_rule`.  Each component
    c is mutated with seed derived from (master_seed, c) so the same
    inputs produce the same result on either party's machine."""
    out = bytearray()
    for c in range(COMPONENTS):
        out += mutate_rule(base_rule, density,
                            seed=(master_seed * 1000003) ^ (c * 2654435761))
    return bytes(out)

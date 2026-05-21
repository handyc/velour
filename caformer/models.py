"""caformer/models.py — DB schema for the workshop.

Components themselves are defined in code (caformer/components.py) so
their design notes are checked into git rather than living as fragile
DB rows.  The DB only stores user *experiments* — when an interactive
demo on a component page is run, the inputs / outputs / score get
persisted so a researcher can come back later and compare runs.
"""

from __future__ import annotations
from django.db import models


class Experiment(models.Model):
    """One run of a component's interactive demo."""
    component = models.CharField(
        max_length=40,
        help_text='Slug of the component (embedding, attention, ...).')
    pact_slug = models.CharField(
        max_length=80, blank=True,
        help_text='Optional spoeqi pact backing this experiment.')
    title     = models.CharField(max_length=120, blank=True)
    notes     = models.TextField(blank=True)

    inputs    = models.JSONField(default=dict, blank=True)
    outputs   = models.JSONField(default=dict, blank=True)
    metrics   = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.component} · {self.title or self.created_at:%Y-%m-%d %H:%M}'


class TrainedModel(models.Model):
    """One evolved CAformer model — the 10 rule tables that
    ca_forward_qkv needs (q, k, v, score, mix, merge, mlp, norm,
    output, embed) plus the metadata to reproduce the run.

    Each rule is a 16,384-byte ``BinaryField``; the whole model is
    ~160 KB on disk.  The chat / DMN endpoints accept ``?model=<slug>``
    to load these rules instead of the random defaults so users can
    swap between a freshly-evolved model and the random baseline
    without restarting anything.
    """
    name        = models.CharField(max_length=80, unique=True)
    slug        = models.SlugField(max_length=80, unique=True)
    notes       = models.TextField(blank=True)

    # The 10 rule tables.  Each is exactly 16,384 bytes (uint8 0..3).
    rule_q      = models.BinaryField()
    rule_k      = models.BinaryField()
    rule_v      = models.BinaryField()
    rule_score  = models.BinaryField()
    rule_mix    = models.BinaryField()
    rule_merge  = models.BinaryField()
    rule_mlp    = models.BinaryField()
    rule_norm   = models.BinaryField()
    rule_output = models.BinaryField()
    rule_embed  = models.BinaryField()

    # Reproducibility + history.
    corpus_excerpt = models.TextField(
        blank=True,
        help_text='First ~500 chars of the training corpus, kept so '
                  'the model can be re-trained on roughly the same data.')
    vocab_size  = models.PositiveIntegerField(default=256)
    n_blocks    = models.PositiveIntegerField(default=2)
    pop_size    = models.PositiveIntegerField(default=8)
    generations = models.PositiveIntegerField(default=6)
    final_fitness = models.FloatField(default=0.0)
    history_json  = models.JSONField(default=list, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.name} ({self.final_fitness:.3f})'

    def as_genome(self):
        """Materialise the 10 rule blobs as a {name: ndarray} genome
        dict — the same shape the GA produces, so the chat endpoint
        can drop it straight into ca_forward_qkv kwargs."""
        import numpy as np
        from .ga import FULL_STACK_NAMES
        rules = {
            'q':      self.rule_q,      'k':      self.rule_k,
            'v':      self.rule_v,      'score':  self.rule_score,
            'mix':    self.rule_mix,    'merge':  self.rule_merge,
            'mlp':    self.rule_mlp,    'norm':   self.rule_norm,
            'output': self.rule_output, 'embed':  self.rule_embed,
        }
        return {n: np.frombuffer(bytes(rules[n]), dtype=np.uint8).copy()
                for n in FULL_STACK_NAMES}

    def rule_diversity(self):
        """Return how independent the 10 rule LUTs actually are.

        A whole-stack GA can converge to "collapsed" solutions where
        several of the named rule slots end up byte-identical — the
        component pipeline then runs only a handful of distinct CA
        dynamics under different labels.  This method makes that
        visible.

        Returns a dict with:
            distinct_count: number of byte-distinct LUTs (1..10).
            groups:         list of lists, each inner list is a set
                              of slot names that share one LUT.
            mean_pairwise_match: average per-byte equality across all
                              ⁹C₂ = 45 rule pairs (0.25 = uncorrelated
                              K=4 baseline; 1.00 = all identical).
        """
        import numpy as np
        g = self.as_genome()
        names = list(g.keys())
        groups, seen = [], [False] * len(names)
        for i, ni in enumerate(names):
            if seen[i]:
                continue
            group = [ni]
            seen[i] = True
            for j in range(i + 1, len(names)):
                if not seen[j] and np.array_equal(g[ni], g[names[j]]):
                    group.append(names[j])
                    seen[j] = True
            groups.append(group)
        # Mean pairwise byte-equality
        total_match = 0
        n_pairs = 0
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                total_match += int((g[names[i]] == g[names[j]]).sum())
                n_pairs += 1
        size = g[names[0]].size
        return {
            'distinct_count': len(groups),
            'groups':         groups,
            'mean_pairwise_match': total_match / (n_pairs * size),
        }


class ChatTurn(models.Model):
    """One round of user→CA conversation, kept verbatim so the GA can
    later train on the user's own chat history.

    Every chat reply persists a row.  ``training_corpus()`` collapses
    them into one long string suitable for ``make_text_fitness``.  The
    point: anything the user types into chat becomes future training
    data without an extra step — close the conversational/training loop.
    """
    user = models.ForeignKey(
        'auth.User', on_delete=models.CASCADE,
        related_name='caformer_chat_turns')
    prompt   = models.TextField()
    reply    = models.TextField(blank=True)
    model_slug = models.CharField(max_length=80, blank=True)
    backbone   = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.user.username} · {self.prompt[:40]}'

    @classmethod
    def training_corpus(cls, user, *, max_chars: int = 200_000) -> str:
        """Build a training corpus from this user's chat turns.
        Format: alternating ``user: …\\nca: …\\n\\n`` blocks so the
        model learns the dialog shape, not just a flat byte stream."""
        rows = list(cls.objects.filter(user=user)
                                 .order_by('created_at')
                                 .values_list('prompt', 'reply'))
        if not rows:
            return ''
        parts = []
        total = 0
        for prompt, reply in rows:
            chunk = f'user: {prompt or ""}\nca: {reply or ""}\n\n'
            parts.append(chunk)
            total += len(chunk)
            if total > max_chars:
                break
        return ''.join(parts)[:max_chars]


class ComponentChampion(models.Model):
    """Best-so-far rule-table bundle for one of the 8 caformer
    components, produced by the per-component autotournament loop.

    A "bundle" is one or more 16,384-byte rule tables concatenated in
    the order specified by ``caformer.component_fitness.COMPONENT_SPECS
    [slug].rules``.  For single-rule components (embedding, norm, mlp,
    output, projection-as-Q) the bundle is one rule = 16,384 bytes.
    For composites (self_attention = 5 rules, transformer = 7 rules)
    the bundle is up to 7 × 16,384 = 114,688 bytes.

    Lineage: each champion can point to a ``parent`` — the champion
    it was warm-started from.  The autotournament loop sets this so
    you can walk the lineage chain backwards from any current champion
    to its founding ancestor.
    """
    component_slug = models.CharField(max_length=40, db_index=True,
                                        help_text='one of COMPONENT_SPECS keys')
    rules_blob     = models.BinaryField()
    rule_names_csv = models.CharField(max_length=120, default='',
                                        help_text='comma-separated rule names in '
                                                    'on-disk order; matches '
                                                    'COMPONENT_SPECS[slug].rules')
    fitness        = models.FloatField(db_index=True)
    parent         = models.ForeignKey('self', null=True, blank=True,
                                         on_delete=models.SET_NULL,
                                         related_name='children')
    generation     = models.PositiveIntegerField(default=0,
                                                   help_text='how many lineage '
                                                              'hops from a random '
                                                              'ancestor')
    run_label      = models.CharField(max_length=40, blank=True,
                                        help_text='tag for the autotournament run '
                                                    'that produced this champion')
    ga_pop_size    = models.PositiveIntegerField(default=0)
    ga_generations = models.PositiveIntegerField(default=0)
    eval_count     = models.PositiveIntegerField(default=0,
                                                   help_text='how many fitness '
                                                              'evals were spent on '
                                                              'this champion')
    notes          = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [
            models.Index(fields=['component_slug', '-fitness']),
        ]

    def __str__(self):
        return (f'{self.component_slug} g{self.generation} '
                f'f={self.fitness:.4f}')

    def rule_table(self, name):
        """Return one of this bundle's rule tables by name as a
        numpy uint8 array of length 16,384."""
        import numpy as np
        names = self.rule_names_csv.split(',')
        try:
            idx = names.index(name)
        except ValueError:
            raise KeyError(
                f'{name!r} not in champion bundle '
                f'(have {names!r})')
        blob = bytes(self.rules_blob)
        start = idx * 16_384
        return np.frombuffer(blob[start:start + 16_384], dtype=np.uint8).copy()

    def genome(self):
        """Return the full bundle as a {name: ndarray} dict."""
        return {n: self.rule_table(n) for n in self.rule_names_csv.split(',')}

    @classmethod
    def best_for(cls, component_slug):
        """Top-fitness champion for the named component, or None."""
        return (cls.objects.filter(component_slug=component_slug)
                              .order_by('-fitness', '-created_at')
                              .first())
        """Build a training corpus from this user's chat turns.
        Format: alternating ``user: …\\nca: …\\n\\n`` blocks so the
        model learns the dialog shape, not just a flat byte stream."""
        rows = list(cls.objects.filter(user=user)
                                 .order_by('created_at')
                                 .values_list('prompt', 'reply'))
        if not rows:
            return ''
        parts = []
        total = 0
        for prompt, reply in rows:
            chunk = f'user: {prompt or ""}\nca: {reply or ""}\n\n'
            parts.append(chunk)
            total += len(chunk)
            if total > max_chars:
                break
        return ''.join(parts)[:max_chars]


class QRPair(models.Model):
    """One (prompt, expected_response) pair the QR trainer evolves
    a CAformer to produce exactly.

    The trainer (``caformer.qr_trainer.train_pair``) is a long-running
    multi-phase loop: GA bursts, polish, periodic random restarts when
    progress stalls.  After each improvement it writes the best
    genome's 10 rule tables back into ``best_genome_blob`` (10 ×
    16,384 bytes concatenated in FULL_STACK_NAMES order) and records
    what the model now generates in ``best_output``.

    When ``best_exact`` flips to True, the model produces ``expected``
    byte-for-byte from ``prompt`` under temperature-0 argmax sampling.
    That's the signal the user wants for "hi → hello".
    """
    prompt   = models.CharField(max_length=200)
    expected = models.CharField(max_length=400)
    n_blocks = models.PositiveSmallIntegerField(default=1)
    notes    = models.TextField(blank=True)
    label    = models.CharField(max_length=40, blank=True,
                                  help_text='free-form tag, e.g. a training '
                                              "run's name")

    # Updated by the trainer on every improvement.  ``best_genome_blob``
    # is the concatenated 10 rule tables; ``None`` until the first
    # training cycle saves something.
    best_fitness = models.FloatField(default=-1e9)
    best_genome_blob = models.BinaryField(null=True, blank=True)
    best_output = models.CharField(max_length=400, blank=True,
                                     help_text='temperature-0 argmax output '
                                                  'of the best genome on prompt')
    best_exact  = models.BooleanField(default=False)
    n_evals     = models.PositiveIntegerField(default=0)
    total_seconds = models.FloatField(default=0.0)
    restarts    = models.PositiveIntegerField(default=0)
    last_phase  = models.CharField(max_length=24, blank=True,
                                     help_text='ga / polish / restart / done')

    deployed_slug = models.CharField(max_length=80, blank=True,
                                         help_text='slug of the TrainedModel '
                                                      'this pair has been '
                                                      'deployed to (if any)')

    # Positional-mode storage: when the trainer was run with
    # ``--positional``, the base 10 rules go in best_genome_blob and the
    # N per-position output rules (one per target byte) are packed here
    # back-to-back.  ``len(positional_output_blob) == n_target_bytes ×
    # 16,384``.  Inference uses positional_output_blob[i] for output
    # position i; falls back to best_genome_blob's output rule when
    # this field is empty (legacy single-rule pairs).
    positional_output_blob = models.BinaryField(null=True, blank=True)

    # board128 positional storage: N per-position 16,384-byte rules,
    # one per byte of the expected response.  Validated 2026-05-18:
    # combines 128×128 board bandwidth (full 4096-char prompt fits)
    # with per-position decomposition (each rule = single-byte target,
    # tractable in 10-50s).  When non-empty, dispatch prefers these
    # over positional_output_blob.  Tick count is fixed at 128 to
    # match board dimensions.
    board128_rules_blob = models.BinaryField(null=True, blank=True)
    board128_exact      = models.BooleanField(default=False)
    board128_ticks      = models.PositiveSmallIntegerField(default=128)

    # Multi-resolution storage hierarchy: optional smaller-board
    # copies of the same chain at coarser resolutions.  Each blob is
    # a concatenation of N per-position rules at the listed side
    # length.  These coexist with board128 — small chains act as
    # error-correctors for the big chain (user framing 2026-05-19)
    # and as cheap fallbacks when the big chain hasn't been trained
    # yet.  Storage cost of all four together is < 8 % of board128
    # alone.  See caformer/multires.py for the scaling primitives.
    b064_rules_blob = models.BinaryField(null=True, blank=True)  # 64×64
    b032_rules_blob = models.BinaryField(null=True, blank=True)  # 32×32
    b016_rules_blob = models.BinaryField(null=True, blank=True)  # 16×16
    b008_rules_blob = models.BinaryField(null=True, blank=True)  # 8×8

    # cell8 + 256×256 storage.  The 8→1 rule shape (65,536-byte LUT)
    # paired with a 256×256 K=4 board (65,536 cells) preserves the
    # LUT-as-board ouroboros symmetry that we lose on 128×128.
    # N per-position cell8 rules concatenated; ``len(cell8_b256_rules_blob)
    # == n_target_bytes × 65,536``.  Coexists with board128_rules_blob —
    # both stay populated, dispatcher chooses (via ?engine=cell8 or
    # priority order).  See caformer/board256.py for the trainer +
    # caformer/io/rule_blob.py for the on-disk merge format.
    cell8_b256_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b256_exact      = models.BooleanField(default=False)
    cell8_input_source    = models.CharField(max_length=16, blank=True,
        default='off',
        choices=[('off',       'port held at 0 (no modulation)'),
                 ('dmn',       'DMN heartbeat tick parity'),
                 ('router',    'router 2-bit category'),
                 ('prev_byte', 'previous chain output cell')])

    # Cell8 multi-resolution storage hierarchy.  Same shape as the
    # 7→1 multires (b008..b064 in this model) but for cell8 rules.
    # Each blob is N per-position 65,536-byte cell8 LUTs at the
    # specified board side.  Used for fast cell8 inference dispatch:
    # tier-auto picks the smallest tier with cell8_*_exact = True.
    # See caformer/cell8_multires.py.
    cell8_b008_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b008_exact      = models.BooleanField(default=False)
    cell8_b016_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b016_exact      = models.BooleanField(default=False)
    cell8_b032_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b032_exact      = models.BooleanField(default=False)
    cell8_b064_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b064_exact      = models.BooleanField(default=False)
    cell8_b128_rules_blob = models.BinaryField(null=True, blank=True)
    cell8_b128_exact      = models.BooleanField(default=False)

    last_queried_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-best_exact', '-best_fitness', '-updated_at')

    def __str__(self):
        return (f'{self.prompt!r} → {self.expected!r} '
                  f'(fit {self.best_fitness:.3f}'
                  f'{" ✓" if self.best_exact else ""})')

    def best_genome(self):
        """Reconstruct the genome dict from ``best_genome_blob``,
        or None if not yet trained."""
        if not self.best_genome_blob:
            return None
        import numpy as np
        from .ga import FULL_STACK_NAMES
        blob = bytes(self.best_genome_blob)
        out = {}
        for i, n in enumerate(FULL_STACK_NAMES):
            s = i * 16_384
            out[n] = np.frombuffer(blob[s:s + 16_384],
                                       dtype=np.uint8).copy()
        return out

    def is_positional(self):
        """True when this pair was trained with per-position output rules."""
        blob = self.positional_output_blob
        return bool(blob) and len(bytes(blob)) >= 16_384

    def positional_output_rules(self):
        """Yield the N per-position output rules.  None if not in
        positional mode."""
        if not self.is_positional():
            return None
        import numpy as np
        blob = bytes(self.positional_output_blob)
        n = len(blob) // 16_384
        return [np.frombuffer(blob[i * 16_384:(i + 1) * 16_384],
                                  dtype=np.uint8).copy()
                for i in range(n)]

    def is_board128(self):
        """True when this pair has board128 per-position rules
        trained.  Dispatch prefers board128 over legacy positional."""
        blob = self.board128_rules_blob
        return bool(blob) and len(bytes(blob)) >= 16_384

    def board128_rules(self):
        """Yield the N board128 per-position rules.  None if not in
        board128 mode."""
        if not self.is_board128():
            return None
        import numpy as np
        blob = bytes(self.board128_rules_blob)
        n = len(blob) // 16_384
        return [np.frombuffer(blob[i * 16_384:(i + 1) * 16_384],
                                  dtype=np.uint8).copy()
                for i in range(n)]

    def is_cell8_b256(self):
        """True when this pair has cell8+256 per-position rules
        stored.  Dispatch may prefer these (when ?engine=cell8) but
        defaults to board128 since cell8 corpus retrain is gradual."""
        blob = self.cell8_b256_rules_blob
        return bool(blob) and len(bytes(blob)) >= 65_536

    def cell8_b256_rules(self):
        """Yield the N cell8 per-position rules (65,536 bytes each).
        None if cell8 rules not stored."""
        if not self.is_cell8_b256():
            return None
        import numpy as np
        blob = bytes(self.cell8_b256_rules_blob)
        n = len(blob) // 65_536
        return [np.frombuffer(blob[i * 65_536:(i + 1) * 65_536],
                                  dtype=np.uint8).copy()
                for i in range(n)]

    def cell8_rules_at_tier(self, tier: str):
        """Yield this pair's cell8 per-position rules at the requested
        multires tier ('b008', 'b016', 'b032', 'b064', 'b128', 'b256').
        Returns None if that tier isn't populated."""
        field = f'cell8_{tier}_rules_blob'
        if not hasattr(self, field):
            return None
        blob = getattr(self, field)
        if not blob or len(bytes(blob)) < 65_536:
            return None
        import numpy as np
        blob = bytes(blob)
        n = len(blob) // 65_536
        return [np.frombuffer(blob[i * 65_536:(i + 1) * 65_536],
                                  dtype=np.uint8).copy()
                for i in range(n)]

    def best_cell8_tier(self):
        """Cheapest cell8 tier with _exact=True, or None if no cell8
        tier is exact.  Used by ?engine=cell8&tier=auto dispatch."""
        for tier in ('b008', 'b016', 'b032', 'b064', 'b128', 'b256'):
            if getattr(self, f'cell8_{tier}_exact', False):
                return tier
        return None


# ─── Harness ────────────────────────────────────────────────────────


class PersonalityModule(models.Model):
    """A named personality module — either defines one *axis* of the
    PersonalityState 4-tuple, or *presets* one specific 4-tuple.

    The harness's PersonalityState has four axes:

      drive       (motivation / why-it-speaks)        — d'Ansembourg
      expression  (rhetorical style / how-it-sounds)  — David Angel
      relation    (intimacy / who-we-are-to-each-other) — Coaching
      lens        (filter on incoming message)        — Schulz von Thun

    Each axis has 4 values (K=4 alignment).  A complete personality
    state = (drive, expression, relation, lens) — 4 bytes, 256
    distinct compositions.  This is the same shape as a boardstack4
    cascade path, so the cascade's 4-tuple output can be reinterpreted
    as a PersonalityState directly.

    Module ``kind`` distinguishes the two roles:

      'axis'   — defines one axis; subroutes are the 4 values of that
                  axis (axis_slug must be drive/expression/relation/lens).
                  Examples: d'Ansembourg, David Angel, Coaching,
                  Schulz von Thun.
      'preset' — defines a specific 4-tuple as a named personality.
                  state_vector must be a 4-element list [d,e,r,l].
                  Examples: Velour, Techbro, Isaacs, Grice — each
                  also carries 4 named *modes* (one preset per
                  subroute, since each subroute is a distinct mood).

    A HarnessProfile points to a preset via personality_module_slug;
    the harness uses that preset's state_vector as its initial /
    default PersonalityState."""

    KIND_CHOICES = (('axis', 'axis (defines one dimension)'),
                    ('preset', 'preset (named 4-tuple)'))
    AXIS_CHOICES = (
        ('drive',      'drive (motivation)'),
        ('expression', 'expression (style)'),
        ('relation',   'relation (intimacy)'),
        ('lens',       'lens (perception filter)'),
    )

    slug = models.SlugField(
        max_length=64, unique=True,
        help_text='Stable identifier, e.g. "velour", "david-angel".')
    name = models.CharField(
        max_length=80,
        help_text='Display name, e.g. "Velour", "David Angel".')
    description = models.TextField(
        blank=True,
        help_text='Short character sketch of the personality.')
    subroutes = models.JSONField(
        default=list,
        help_text='List of 4 dicts: '
                  '[{label, tokens: [...], notes}, ...].  '
                  'tokens are short (≤ 4 char) keyword matches on '
                  'word boundaries.  Order matters — index 0..3 maps '
                  'to depth-1 branch indices under personality (0).')
    kind = models.CharField(
        max_length=10, choices=KIND_CHOICES, default='preset',
        help_text='axis: defines one dimension of PersonalityState. '
                  'preset: defines a named 4-tuple in that space.')
    axis_slug = models.CharField(
        max_length=20, choices=AXIS_CHOICES, blank=True,
        help_text='If kind=axis, which dimension (drive/expression/'
                  'relation/lens).  Otherwise empty.')
    state_vector = models.JSONField(
        default=list,
        help_text='If kind=preset, the default 4-tuple [d, e, r, l] '
                  '(each 0..3) this module evokes.  Each of the 4 '
                  'subroutes may also carry its own state_vector — '
                  'a different mood within this persona.')

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['slug']

    def __str__(self):
        return f'{self.name} ({self.slug})'


class HarnessProfile(models.Model):
    """A named configuration of the caformer harness.

    The deterministic core (CA rules + QRPair dispatcher) is fixed.
    Everything *around* it — persona, system prompt, what gets
    injected as context, which spinner verbs roll, how the prefilter
    routes — lives here.  One profile = one personality you can pin
    to a chat surface.

    Per-category spinner verbs are stored as a single JSON blob
    keyed by integer category (0..3, mapping to PERSONALITY /
    INFORMATION / ACTION / META).  When None or partial, the
    harness falls back to caformer.harness.verbs.DEFAULT_VERBS.
    """

    slug = models.SlugField(max_length=64, unique=True)
    persona_name = models.CharField(
        max_length=80, blank=True,
        help_text='Short display name, e.g. "Alice", "the librarian".')
    persona_description = models.TextField(
        blank=True,
        help_text='2–5 sentence character sketch.  Voice, values, '
                  'specialities.  Forms the bulk of the system prompt.')
    system_prompt_extra = models.TextField(
        blank=True,
        help_text='Additional instructions appended after the persona '
                  'description.  Use for capability claims, refusal '
                  'posture, formatting rules.')

    inject_cwd      = models.BooleanField(default=False)
    inject_time     = models.BooleanField(default=True)
    inject_git      = models.BooleanField(default=False)
    inject_identity = models.BooleanField(default=True,
        help_text='Pull current Velour identity mood into the '
                  'context block (soft-fails if identity app absent).')

    PREFILTER_CHOICES = (
        ('router',      'router (single CA classifier, majority vote)'),
        ('boardstack4', 'boardstack4 (4-board sequential cascade)'),
        ('multiscale',  'multiscale boardstack4 (sides 4/8/16/32, XOR combined)'),
        ('byte_router', 'byte_router (4×4 cell8 cascade with trained permutation)'),
    )

    personality_module_slug = models.CharField(
        max_length=64, blank=True,
        help_text='Optional slug of a PersonalityModule.  When set, '
                  "this profile's personality route descends into that "
                  "module's 4 subroutes instead of the shared PICM "
                  "tree's personality children.")
    prefilter_mode = models.CharField(
        max_length=16, choices=PREFILTER_CHOICES, default='router',
        help_text='Which deterministic prefilter classifies the prompt. '
                  'boardstack4 emits a 4-colour path for richer routing.')

    spinner_verbs_json = models.JSONField(
        null=True, blank=True,
        help_text='Optional per-category verb overrides.  Map '
                  '{"0":[...],"1":[...],"2":[...],"3":[...]}.')

    notes = models.TextField(blank=True)
    is_default = models.BooleanField(default=False,
        help_text='Used by /caformer/harness/ when no slug is pinned.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-is_default', 'persona_name', 'slug')

    def __str__(self) -> str:
        if self.persona_name:
            return f'{self.persona_name} ({self.slug})'
        return self.slug

    def spinner_verbs_by_category(self):
        """Return a dict[int → tuple[str]] suitable for
        caformer.harness.verbs.pick().  Falls back to the module
        default for any category not overridden in the JSON blob."""
        from caformer.harness.verbs import DEFAULT_VERBS
        override = self.spinner_verbs_json or {}
        out = {}
        for cat in (0, 1, 2, 3):
            v = override.get(str(cat)) or override.get(cat)
            if v:
                out[cat] = tuple(v)
            else:
                out[cat] = DEFAULT_VERBS[cat]
        return out


class PICMVocab(models.Model):
    """Per-Intent Character Map — the vocabulary store for one
    boardstack4 agent.

    Each routing colour (0..3 = personality / information / command /
    meta) gets its own PICMVocab.  The vocab is a list of short tokens
    (≤ ``bytes_per_token`` ASCII chars, default 4) that the agent
    recognises and emits.

    The 128×128 K=4 "board" view is *derived* from the token list:
    each token packs into ``bytes_per_token × 4`` cells (2 bits per
    cell), occupying ``token_count`` slots within the 16,384-cell
    board.  Future phases may evolve the board with a CA and read
    tokens back out; for now the JSON list is the source of truth.

    Why JSON-first and not raw-blob-first: tokens are human-edited
    in admin, and we want changes to be visible immediately without
    re-packing.  ``caformer.harness.picm.pack_board()`` produces the
    binary board on demand."""

    AGENT_CHOICES = (
        (0, 'personality'),
        (1, 'information'),
        (2, 'command'),
        (3, 'meta'),
    )
    agent_color = models.PositiveSmallIntegerField(
        choices=AGENT_CHOICES, unique=True,
        help_text='Which boardstack4 routing colour this vocab belongs to.')
    bytes_per_token = models.PositiveSmallIntegerField(
        default=4,
        help_text='Max ASCII bytes per token.  4 = 1024 tokens fit '
                  'in 128×128 K=4; 8 = 512 tokens.')
    token_count = models.PositiveSmallIntegerField(
        default=1024,
        help_text='Max vocab size.  16,384 cells / (bytes_per_token × 4) '
                  'is the upper bound.')
    tokens_json = models.JSONField(
        default=list, blank=True,
        help_text='Ordered list of token strings.  Truncated to '
                  'bytes_per_token chars at pack time; longer entries '
                  'lose their tail.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('agent_color',)

    def __str__(self) -> str:
        n = len(self.tokens_json or [])
        return f'PICM[{self.get_agent_color_display()}] {n} tokens'

    def tokens(self) -> list[str]:
        """Normalise the JSON list to a Python list of strings,
        truncated to bytes_per_token bytes each."""
        out: list[str] = []
        for t in (self.tokens_json or []):
            s = str(t)[:self.bytes_per_token]
            out.append(s)
        return out


class TemplatePattern(models.Model):
    """A slot-templated p → q mapping owned by one boardstack4 agent.

    The pattern field is a *prompt template* with bracketed slots,
    e.g. ``look up [X]`` or ``how many [thing] are in [container]``.
    A user prompt matches this row if the literal parts align and
    every slot captures a non-empty span.

    The ``output`` field is an *answer template* referencing the
    same slot names; on match, slot values are substituted in.
    The combination gives parametric coverage with one trained row:

        pattern  = 'look up [X]'
        output   = 'https://en.wikipedia.org/wiki/[X]'
        prompt   = 'look up dogs'   → 'https://en.wikipedia.org/wiki/dogs'
        prompt   = 'look up Velour' → 'https://en.wikipedia.org/wiki/Velour'

    Multiple patterns may match an incoming prompt; the harness picks
    the most *specific* one (longest literal portion + fewest slots),
    yielding an implicit decision-tree shape from a flat table.

    Author tip: keep slot names short (single uppercase letters or
    short snake_case).  Slot names must match between ``pattern``
    and ``output``; unused output slots are emitted literally."""

    AGENT_CHOICES = (
        (0, 'personality'),
        (1, 'information'),
        (2, 'command'),
        (3, 'meta'),
    )
    agent_color = models.PositiveSmallIntegerField(choices=AGENT_CHOICES)
    pattern = models.CharField(
        max_length=240,
        help_text='Prompt pattern with [SlotName] markers, e.g. '
                  "'look up [X]' or 'how many [item]'.")
    output = models.TextField(
        help_text='Answer template referencing the same slot names. '
                  'On match, slot values are substituted in.')
    priority = models.PositiveSmallIntegerField(
        default=5,
        help_text='Lower priority wins ties between equally specific '
                  'patterns.  1 = highest, 9 = lowest.')
    is_active = models.BooleanField(default=True)
    confidence = models.FloatField(
        default=0.7,
        help_text='Confidence the harness reports for matches from '
                  'this template.  0..1.  Templates with no real '
                  'data backing them (stubs) should be ≤ 0.5.')
    handler_name = models.CharField(
        max_length=64, blank=True,
        help_text='Optional name of a registered live-data handler '
                  '(see caformer.harness.handlers.HANDLERS).  When '
                  'set, the entire ``output`` field is replaced with '
                  'the handler\'s return value at match time.  '
                  '``output`` is still used as a comment / fallback '
                  'if the handler is unknown.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('agent_color', 'priority', '-updated_at')
        indexes = [
            models.Index(fields=['agent_color', 'is_active']),
        ]

    def __str__(self) -> str:
        return f'[{self.get_agent_color_display()}] {self.pattern}'


class PICMNode(models.Model):
    """One node in the hierarchical PICM tree.

    The tree is rooted implicitly; top-level nodes have ``tree_path``
    values '0', '1', '2', '3' (one per boardstack4 routing colour).
    Children append a dot + branch index: '1.0', '1.0.2', etc.
    Up to four levels deep (4^4 = 256 leaves).

    Descent at runtime walks one level at a time: at each level, every
    candidate child node's ``relevance_tokens`` is scored against the
    prompt; the child with the most matches wins.  If no children
    match, descent stops at the current node.

    Leaves connect to a labelled subset of QRPairs (via
    ``qrpair_label``) and a tag-filtered set of TemplatePatterns (via
    ``template_tag``).  When a leaf is hit, only those subsets are
    consulted for dispatch — giving each leaf a *specialised* response
    repertoire."""

    tree_path = models.CharField(
        max_length=16, unique=True,
        help_text='Dot-separated path of K=4 branch indices.  '
                  "Top level: '0'..'3'.  Children: '0.2', '1.3.0', etc. "
                  'Max depth 4 (= 8 chars including dots).')
    label = models.CharField(
        max_length=80,
        help_text='Short human-readable name for this node, e.g. '
                  "'information', 'who-queries', 'historical-person'.")
    description = models.TextField(blank=True)
    relevance_tokens = models.JSONField(
        default=list,
        help_text='Tokens whose presence in the prompt signals this '
                  'branch is the right descent.  Short (≤ 4 char) '
                  'tokens, matched on word boundaries case-insensitively.')
    is_leaf = models.BooleanField(
        default=False,
        help_text='When True, descent halts here and the harness '
                  'dispatches using this node\'s qrpair_label + '
                  'template_tag scopes.')
    qrpair_label = models.CharField(
        max_length=80, blank=True,
        help_text='When set, leaf dispatch consults only QRPairs '
                  'with this exact label value.')
    template_tag = models.CharField(
        max_length=80, blank=True,
        help_text='When set, leaf dispatch consults only '
                  'TemplatePatterns whose notes field contains this '
                  'tag (case-insensitive substring).')
    confidence = models.FloatField(
        default=0.7,
        help_text='Confidence reported when this leaf produces a '
                  'reply.  0..1.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('tree_path',)
        indexes = [
            models.Index(fields=['tree_path']),
        ]

    def __str__(self) -> str:
        return f'PICMNode {self.tree_path or "(root)"} · {self.label}'

    @property
    def depth(self) -> int:
        """0 for top-level nodes (path '0'..'3'), 1 for '0.0'..'3.3'."""
        if not self.tree_path:
            return -1
        return self.tree_path.count('.')

    @property
    def branch_index(self) -> int:
        """The K=4 colour this node represents at its level (last
        component of the path)."""
        if not self.tree_path:
            return -1
        return int(self.tree_path.rsplit('.', 1)[-1])

    @property
    def parent_path(self) -> str:
        """Path of the parent node, or '' if this is top-level."""
        if '.' not in self.tree_path:
            return ''
        return self.tree_path.rsplit('.', 1)[0]

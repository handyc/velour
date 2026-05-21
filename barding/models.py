"""barding — comparative study of LLM "harnesses".

Two layers in one app:

1. **Study models** (`Harness`, `Technique`, `Observation`,
   `DistillationProposal`) catalogue how different LLM harnesses —
   Claude Code CLI, ChatGPT web, Claude.ai, Cursor, Aider, … —
   manufacture the *feel* of talking to a person on top of a
   deterministic model.  Each `Observation` ties one `Harness` to one
   `Technique` with evidence (a binary string, a leaked prompt, a
   source-code excerpt, a screenshot path).  `DistillationProposal`
   captures the design decision for porting that technique into the
   caformer harness.

2. **Claude Code operator tools** (`SettingsScope`, `BundlePatchWish`)
   — the original barding scope.  Settings.json is the source of
   truth on disk; the rows just record which paths we manage from
   the UI.  These now serve as the deepest live-observation set for
   the Claude Code CLI harness profile.
"""

from __future__ import annotations

from django.db import models


SCOPE_CHOICES = (
    ('user',    'user (~/.claude/settings.json)'),
    ('project', 'project (<repo>/.claude/settings.json)'),
    ('local',   'local  (<repo>/.claude/settings.local.json)'),
)


class SettingsScope(models.Model):
    """One row per settings.json path we know how to read/write."""

    name = models.CharField(max_length=32, choices=SCOPE_CHOICES, unique=True)
    path = models.CharField(max_length=512,
                            help_text='Absolute path to a settings.json file.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self) -> str:
        return f'{self.get_name_display()}'


PATCH_KINDS = (
    ('verb',    'thinking verb'),
    ('spinner', 'spinner glyph'),
    ('other',   'other binary string'),
)


class BundlePatchWish(models.Model):
    """A planned binary-string substitution.  Never auto-applied:
    Claude Code ships as a single ELF and every upgrade clobbers any
    in-place patch.  The UI surfaces this row as a paste-able recipe
    the operator may run by hand after each upgrade."""

    kind = models.CharField(max_length=16, choices=PATCH_KINDS,
                            default='verb')
    target = models.CharField(max_length=256,
                              help_text='Exact string currently in the binary.')
    replacement = models.CharField(
        max_length=256,
        help_text='Desired replacement.  Must be ≤ len(target) bytes '
                  'unless you intend to relocate (advanced).')
    notes = models.TextField(blank=True)
    applied = models.BooleanField(default=False,
                                  help_text='Operator-toggled flag — purely '
                                            'informational, the row is never '
                                            'auto-applied.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self) -> str:
        return f'{self.get_kind_display()}: {self.target!r} → {self.replacement!r}'

    @property
    def length_ok(self) -> bool:
        return len(self.replacement.encode('utf-8')) <= len(self.target.encode('utf-8'))

    def sed_recipe(self, binary_path: str) -> str:
        """A copy-paste sed/printf one-liner the operator can run after
        each Claude Code upgrade.  Pads the replacement with NULs to
        match the original length so offsets don't shift."""
        # Padding to keep the binary string length constant.
        old = self.target
        new = self.replacement
        pad = len(old.encode('utf-8')) - len(new.encode('utf-8'))
        padded = new + ('\\x00' * pad if pad > 0 else '')
        return (f"# Replace {self.get_kind_display()!s} string in {binary_path}\n"
                f"# Always back up first: cp {binary_path} {binary_path}.bak\n"
                f"python3 -c \"import sys; p=sys.argv[1]; "
                f"d=open(p,'rb').read(); "
                f"old={old.encode('utf-8')!r}; new={padded.encode('utf-8')!r}; "
                f"assert old in d, 'target not found'; "
                f"open(p,'wb').write(d.replace(old, new, 1))\" {binary_path}")


# ─── Comparative-study models ──────────────────────────────────────

SURFACE_CHOICES = (
    ('cli',    'CLI'),
    ('web',    'web app'),
    ('ide',    'IDE plugin'),
    ('api',    'raw API / SDK'),
    ('mobile', 'mobile app'),
    ('mixed',  'multi-surface'),
)


class Harness(models.Model):
    """One LLM harness under study (Claude Code CLI, ChatGPT web, …).

    A *harness* is the layer above the model: prompt construction,
    tool-use loop, streaming UI, persona, memory, context compaction,
    repair language — everything that turns a deterministic next-token
    function into something that feels like a collaborator."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=120)
    vendor = models.CharField(max_length=80, blank=True)
    surface = models.CharField(max_length=12, choices=SURFACE_CHOICES,
                               default='cli')
    is_open_source = models.BooleanField(default=False,
        help_text='True if the harness source is publicly inspectable.')
    summary = models.TextField(blank=True,
        help_text='2–4 sentence orientation: what it is, what makes it '
                  'distinctive as a harness.')
    home_url = models.URLField(blank=True)
    repo_url = models.URLField(blank=True)
    version_seen = models.CharField(max_length=40, blank=True,
        help_text='Version string we last observed (free-form).')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('name',)

    def __str__(self) -> str:
        return self.name


TECHNIQUE_CATEGORIES = (
    ('pregen',   'pre-generation (prompt + context build)'),
    ('instream', 'in-stream (visible during generation)'),
    ('postgen',  'post-generation (repair / hedging / retry)'),
    ('crossturn','cross-turn (memory / compaction / summary)'),
    ('register', 'register / persona (tone, affect, casual)'),
    ('tooluse',  'tool-use loop'),
    ('meta',     'meta / governance (refusals, safety, etc.)'),
)


class Technique(models.Model):
    """A named harness technique that contributes to "feels like a
    person": rotating spinner verbs, mid-thinking summaries, proactive
    clarifying questions, gentle repair language, etc.

    A technique is *substrate-agnostic*: it can be observed across
    many harnesses.  Its presence and quality in a given harness is
    recorded via Observation."""

    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=12, choices=TECHNIQUE_CATEGORIES,
                                default='instream')
    description = models.TextField(blank=True,
        help_text='What the technique is and why it contributes to the '
                  '"magic" feel.  Be concrete.')
    magic_weight = models.FloatField(default=0.5,
        help_text='0..1 — subjective contribution to "feels like a person". '
                  'Used to rank distillation priorities.')
    deterministic_cost = models.CharField(max_length=8, default='?', choices=(
        ('trivial', 'trivial'),
        ('cheap',   'cheap (≤ 1 KB code, no state)'),
        ('medium',  'medium (a few KB or per-turn state)'),
        ('heavy',   'heavy (model dependency or large state)'),
        ('?',       'unknown'),
    ), help_text='Rough cost of implementing this around the deterministic '
                 'caformer core.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-magic_weight', 'name')

    def __str__(self) -> str:
        return self.name


SOURCE_KINDS = (
    ('binary_string', 'string in binary'),
    ('source_code',   'source code / repo file'),
    ('prompt_leak',   'leaked / published system prompt'),
    ('docs',          'vendor docs / blog post'),
    ('screenshot',    'screenshot / observed UI'),
    ('transcript',    'transcript excerpt'),
    ('reasoned',      'reasoned inference (no direct artifact)'),
)


class Observation(models.Model):
    """Evidence that a Harness uses a Technique.  Each row is one
    piece of evidence — we want many of these per (harness, technique)
    so the comparison grid stays honest."""

    harness = models.ForeignKey(Harness, on_delete=models.CASCADE,
                                related_name='observations')
    technique = models.ForeignKey(Technique, on_delete=models.CASCADE,
                                  related_name='observations')
    source_kind = models.CharField(max_length=16, choices=SOURCE_KINDS,
                                   default='reasoned')
    summary = models.CharField(max_length=240,
        help_text='One-line summary: what was observed.')
    evidence = models.TextField(blank=True,
        help_text='Raw evidence — quoted strings, URLs, line refs, paths.')
    confidence = models.FloatField(default=0.7,
        help_text='0..1 — how confident we are the harness really does this.')
    observed_at = models.DateField(null=True, blank=True,
        help_text='When the observation was made (YYYY-MM-DD).')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-confidence', '-created_at')
        indexes = [
            models.Index(fields=['harness', 'technique']),
        ]

    def __str__(self) -> str:
        return f'{self.harness.name} · {self.technique.name}'


DISTILL_DECISIONS = (
    ('include',    'include — port faithfully'),
    ('simplified', 'simplified — port a lighter variant'),
    ('skip',       'skip — not worth the cost'),
    ('research',   'research — undecided, needs experiment'),
)


class DistillationProposal(models.Model):
    """The design decision for porting one Technique into the
    caformer harness.  Together these rows are the actionable plan
    that comes out of the comparative study."""

    technique = models.OneToOneField(Technique, on_delete=models.CASCADE,
                                     related_name='distill')
    decision = models.CharField(max_length=12, choices=DISTILL_DECISIONS,
                                default='research')
    rationale = models.TextField(blank=True,
        help_text='Why this decision.  What we lose if we skip; what we '
                  'gain if we include; what the simplified form looks like.')
    byte_budget = models.PositiveIntegerField(null=True, blank=True,
        help_text='Estimated bytes of code/data the implementation would '
                  'cost.  Helps the low-resource concept stay honest.')
    implementation_notes = models.TextField(blank=True,
        help_text='Concrete plan: which caformer module, what hooks, what '
                  'state, fallback behaviour.')
    priority = models.PositiveSmallIntegerField(default=3,
        help_text='1=ship first, 5=last.  Lets /barding/distill/ rank.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('priority', '-technique__magic_weight')

    def __str__(self) -> str:
        return f'{self.get_decision_display()}: {self.technique.name}'

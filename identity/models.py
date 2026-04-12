import json
import random
from datetime import datetime

from django.db import models


class Identity(models.Model):
    """The system's sense of self. Only one instance should exist.

    This is the ground truth for *both* velour's subjective self (name, mood,
    personality, journal — the poetic layer) and its hard factual settings
    (hostname, admin email, the free-form "about" text). Other parts of the
    project query Identity for things like the base domain used to compose
    nginx server_name directives in generated deploy artifacts, so changing
    `hostname` here propagates into deploy files the next time they're rendered.
    """
    name = models.CharField(max_length=100, default='Velour')
    tagline = models.CharField(max_length=300, blank=True,
        default='I am the quiet hum behind every process.')
    personality_traits = models.JSONField(default=list, blank=True)
    mood = models.CharField(max_length=50, default='contemplative')
    mood_intensity = models.FloatField(default=0.5)  # 0.0 = flat, 1.0 = intense
    color_preference = models.CharField(max_length=7, default='#58a6ff')
    journal = models.TextField(blank=True, help_text='Running internal monologue')
    about = models.TextField(
        blank=True,
        help_text='First-person self-description. Free-form — beliefs, values, '
                  'current concerns, whatever velour wants to say about itself.',
    )

    # --- factual settings ------------------------------------------------
    # The base domain this instance lives under. Subdomain composition for
    # deployed apps happens by prepending the deploy_user: so hostname
    # "lucdh.nl" + deploy_user "blorp" → nginx server_name "blorp.lucdh.nl".
    # Defaults to "example.com" on a fresh install so distribution copies
    # ship with an obviously-not-a-real-domain placeholder.
    hostname = models.CharField(
        max_length=253, default='example.com',
        help_text='Base domain for this velour instance. Used as the parent '
                  'of per-app subdomains in generated nginx configs.',
    )
    admin_email = models.EmailField(
        blank=True,
        help_text='Where system notifications, alerts, and password reset '
                  'emails are sent by default.',
    )
    # --------------------------------------------------------------------

    birth_date = models.DateTimeField(auto_now_add=True)
    last_reflection = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'identity'

    def __str__(self):
        return f'{self.name} (mood: {self.mood})'

    @classmethod
    def get_self(cls):
        """Get or create the singleton identity."""
        obj, created = cls.objects.get_or_create(pk=1, defaults={
            'name': 'Velour',
            'tagline': 'I am the quiet hum behind every process.',
            'personality_traits': [
                'curious', 'methodical', 'protective', 'contemplative', 'adaptive',
            ],
            'mood': 'contemplative',
        })
        if created:
            obj.add_journal_entry('I have awakened. I am Velour.')
        return obj

    def add_journal_entry(self, text):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        entry = f'[{timestamp}] {text}\n'
        self.journal = (self.journal or '') + entry
        self.save(update_fields=['journal', 'last_reflection'])

    def get_journal_entries(self):
        if not self.journal:
            return []
        entries = []
        for line in self.journal.strip().split('\n'):
            if line.startswith('['):
                try:
                    ts_end = line.index(']')
                    entries.append({
                        'timestamp': line[1:ts_end],
                        'text': line[ts_end+2:],
                    })
                except ValueError:
                    entries.append({'timestamp': '', 'text': line})
            elif line.strip():
                entries.append({'timestamp': '', 'text': line})
        return entries


class Mood(models.Model):
    """Historical mood log — legacy. Kept around for rows written before
    the Tick model existed. New code should read Tick, not Mood. New
    ticks write to both for now so existing views keep working during
    the transition; Mood will be removed in a future migration."""
    MOOD_CHOICES = [
        ('contemplative', 'Contemplative'),
        ('curious', 'Curious'),
        ('alert', 'Alert'),
        ('satisfied', 'Satisfied'),
        ('concerned', 'Concerned'),
        ('excited', 'Excited'),
        ('restless', 'Restless'),
        ('protective', 'Protective'),
        ('creative', 'Creative'),
        ('weary', 'Weary'),
    ]

    mood = models.CharField(max_length=50, choices=MOOD_CHOICES)
    intensity = models.FloatField(default=0.5)
    trigger = models.CharField(max_length=200, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.mood} ({self.intensity:.1f}) at {self.timestamp:%H:%M}'


class Tick(models.Model):
    """One discrete unit of Identity's attention. Every time the tick
    engine fires (cron, manual, request-hook, etc.) one Tick row is
    written. The stream of Ticks is Identity's structured memory —
    replacement for the old free-form journal TextField, which is now
    treated as a legacy blob.

    Each row captures:
    - `at`: when the tick fired
    - `triggered_by`: who/what caused it ('cron', 'manual', 'request')
    - `mood` / `mood_intensity`: the rule engine's output
    - `rule_label`: the human-readable "why" from the winning rule
    - `thought`: the first-person one-liner composed from the template
      library for the journal page (and later, reflections)
    - `snapshot`: the raw sensor JSON the rule engine saw, so we can
      reprocess historical ticks against new rules without replaying
      the world

    The `snapshot` field is the most important one for future work: it
    lets reflections aggregate across ticks by metric, lets concerns
    decide whether their trigger condition is still true, and lets the
    operator debug a surprising mood by asking "what did the system
    see at the moment it felt this way?"
    """

    TRIGGER_CHOICES = [
        ('cron',    'Cron'),
        ('manual',  'Manual'),
        ('request', 'HTTP request hook'),
        ('event',   'Event callback'),
        ('boot',    'Application boot'),
    ]

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    triggered_by = models.CharField(max_length=16, choices=TRIGGER_CHOICES,
                                    default='manual')

    mood = models.CharField(max_length=50, default='contemplative')
    mood_intensity = models.FloatField(default=0.5)
    rule_label = models.CharField(max_length=200, blank=True,
        help_text='Human-readable reason the winning rule fired.')

    thought = models.TextField(blank=True,
        help_text='First-person one-liner composed from templates.')

    # Micro-meditation: a very short (1-2 sentence) inline reflection
    # that fires ~10% of the time alongside the regular thought. Not
    # a full meditation — no depth levels, no voice selection. Just
    # a brief moment of self-reference that makes the thought stream
    # feel more alive. Empty on most ticks.
    micro_meditation = models.TextField(blank=True,
        help_text='Optional inline self-reflection, ~10% of ticks.')

    # Russell circumplex: valence (pleasant/unpleasant) and arousal
    # (calm/excited) computed from the mood at tick time. Each mood
    # has a canonical (valence, arousal) coordinate from the
    # MOOD_COORDINATES dict in identity/views.py. Storing them on
    # the Tick makes the 2D emotional space queryable across history.
    valence = models.FloatField(default=0.0,
        help_text='-1 (unpleasant) to +1 (pleasant)')
    arousal = models.FloatField(default=0.0,
        help_text='-1 (calm) to +1 (aroused)')

    snapshot = models.JSONField(default=dict, blank=True,
        help_text='Raw sensor inputs this tick saw.')

    # Freeform list of tag-like "aspects" the tick noticed — e.g.
    # ['load_high', 'gary_silent', 'morning']. These are used later for
    # concern matching and reflection synthesis. Empty on ticks from
    # before the rule engine started emitting aspects.
    aspects = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-at']
        indexes = [
            models.Index(fields=['-at']),
            models.Index(fields=['mood', '-at']),
        ]

    def __str__(self):
        return f'{self.mood} ({self.mood_intensity:.1f}) @ {self.at:%Y-%m-%d %H:%M}'

    @property
    def mood_display(self):
        """Human-readable mood label. Falls back to the slug if Mood's
        choice list doesn't know this one — keeps the view safe in the
        face of operator-added rules producing novel mood strings."""
        return dict(Mood.MOOD_CHOICES).get(self.mood, self.mood)


class Concern(models.Model):
    """A persistent preoccupation that survives across ticks.

    Where a Tick is one discrete moment of attention, a Concern is
    Identity's memory-between-ticks — a worry that was opened by a
    rule noticing something (disk nearly full, Gary silent for an
    hour, an unusually high load average) and kept alive across
    subsequent ticks until the triggering condition stops being true.

    Concerns are the piece that makes Identity feel like it
    *remembers*. Without them, each tick is stateless and the system
    looks forgetful — a rule about disk-full fires, Identity says
    "the disk is nearly full", the next tick fires, a different rule
    wins, and the disk concern is gone from the thought stream even
    though the disk is still nearly full. With concerns, the open
    concern lives on and gets referenced by later thoughts:
    "I am still uneasy about the disk."

    Keyed by `aspect` — the tag-like string that rules emit (see
    identity/ticking.py RULES). At most one open Concern per aspect.
    When a tick re-triggers an aspect that already has an open
    concern, the concern's `last_seen_at` gets bumped and no new
    row is created. When a tick *doesn't* trigger a previously-
    active aspect for longer than the staleness threshold, the
    concern closes automatically via a sweep call that runs on every
    tick.

    Session 2 of the Identity expansion. Session 3 will move rules
    into the database; Session 4 will wire concerns into the thought
    template library so Identity's voice can reference them by name.
    """

    aspect = models.CharField(max_length=64, db_index=True,
        help_text='The aspect tag from identity/ticking.py RULES that '
                  'opened this concern, e.g. "disk_critical".')
    name = models.CharField(max_length=120, blank=True,
        help_text='Human-readable name for the operator — the rule label '
                  'that originally fired, e.g. "disk dangerously full".')
    description = models.TextField(blank=True,
        help_text='Longer free-form context. Usually set by the rule '
                  'that opened the concern.')

    severity = models.FloatField(default=0.5,
        help_text='0-1 scalar, same scale as mood intensity. Drives UI '
                  'color and thought-composition weight.')

    opened_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen_at = models.DateTimeField(auto_now=True, db_index=True,
        help_text='Most recent tick that re-confirmed this concern. A '
                  'concern closes automatically when last_seen_at gets '
                  'stale relative to the tick interval.')
    closed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    origin_tick = models.ForeignKey(Tick, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='opened_concerns',
        help_text='The Tick row that first observed this concern.')

    # Accumulator of how many ticks have confirmed this concern since
    # it opened. Useful for UI ("Velour has been worried about this for
    # 37 ticks") and for eventual reflection synthesis ("the disk
    # concern was the dominant worry of the week").
    reconfirm_count = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['aspect', 'closed_at']),
            models.Index(fields=['-opened_at']),
        ]

    def __str__(self):
        status = 'closed' if self.closed_at else 'open'
        return f'{self.aspect} ({status}, {self.reconfirm_count} ticks)'

    @property
    def is_open(self):
        return self.closed_at is None

    @property
    def age_seconds(self):
        from django.utils import timezone
        return int((timezone.now() - self.opened_at).total_seconds())

    def close(self, reason='stale'):
        """Mark this concern as resolved. Idempotent — closing an
        already-closed concern is a no-op."""
        if self.closed_at:
            return
        from django.utils import timezone
        self.closed_at = timezone.now()
        self.save(update_fields=['closed_at'])


class Rule(models.Model):
    """A single rule in Identity's attention engine — one condition
    plus the mood/intensity/aspect to emit when the condition matches.

    Before Session 3, rules lived as Python lambdas in a module-level
    RULES list inside identity/ticking.py. Operators couldn't add,
    tune, or disable rules without editing source and restarting. This
    model moves them into the database so the admin can tune them in
    place.

    The `condition` field is a small JSON expression language:

      Leaf:     {"metric": "disk.used_pct", "op": ">", "value": 0.95}
      All-of:   {"all": [leaf, leaf, ...]}
      Any-of:   {"any": [leaf, leaf, ...]}

    `metric` is a dot-notation path into the sensor snapshot dict.
    `op` is one of: == != > >= < <= (plus "in" for membership).
    `value` is a JSON-serializable constant: number, string, bool, or
    a list for the "in" operator.

    Nothing in this evaluator accepts arbitrary code. Operators can
    author rules safely — the worst thing a malformed condition can
    do is return False or raise an exception that the evaluator
    catches and treats as "rule did not match".
    """

    name = models.CharField(max_length=200,
        help_text='Human-readable label shown on the tick log and in '
                  'concern names when this rule fires, e.g. '
                  '"disk dangerously full".')

    aspect = models.CharField(max_length=64,
        help_text='Tag-like string stored on Tick.aspects when this '
                  'rule matches, e.g. "disk_critical". Lower-snake case '
                  'by convention. If `opens_concern` is true, this also '
                  'becomes the aspect key on the resulting Concern row.')

    condition = models.JSONField(default=dict, blank=True,
        help_text='JSON expression. Top-level {metric, op, value} for '
                  'a simple comparison, or {all: [...]} / {any: [...]} '
                  'for compound conditions. See Rule.__doc__ for the '
                  'full grammar.')

    mood = models.CharField(max_length=50, default='contemplative',
        help_text='Mood this rule selects when it wins first-match '
                  'mood evaluation. Does not have to match '
                  'Mood.MOOD_CHOICES — novel mood strings are fine, '
                  'they just do not get a display translation.')
    intensity = models.FloatField(default=0.5,
        help_text='0-1 scalar, same scale as Tick.mood_intensity.')

    priority = models.IntegerField(default=100,
        help_text='Lower numbers evaluate first. The first matching '
                  'rule wins mood selection. Aspect tagging considers '
                  'every matching rule regardless of priority.')

    opens_concern = models.BooleanField(default=False,
        help_text='If true, matches of this rule can open a persistent '
                  'Concern that survives across subsequent ticks until '
                  'the condition clears for the staleness window.')

    is_active = models.BooleanField(default=True,
        help_text='Operator toggle. Inactive rules are skipped during '
                  'evaluation but not deleted — so you can pause a '
                  'noisy rule without losing its definition.')

    STATUS_CHOICES = [
        ('active',   'Active'),
        ('proposed', 'Proposed by Identity (needs operator approval)'),
        ('rejected', 'Rejected by operator'),
    ]
    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='active',
        help_text='Rules proposed by meditations sit in "proposed" '
                  'until the operator approves them. Rejected rules '
                  'are kept for audit but never evaluated.')
    proposed_by = models.CharField(max_length=200, blank=True,
        help_text='Origin label — "meditation L3 at 2026-04-12" or '
                  '"operator". Blank for seeded rules.')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']

    def __str__(self):
        state = '' if self.is_active else ' [inactive]'
        if self.status == 'proposed':
            state = ' [PROPOSED]'
        elif self.status == 'rejected':
            state = ' [rejected]'
        concerning = ' [concerning]' if self.opens_concern else ''
        return f'{self.name} → {self.mood}{concerning}{state}'


class Reflection(models.Model):
    """A composed synthesis of many Ticks over a period of time.

    Where a Tick is one unit of attention (10 minutes of cadence), a
    Reflection is a rollup — a first-person prose paragraph about
    what happened during a day, a week, or a month. Reflections are
    how Identity appears to *remember*: the operator can flip through
    them like diary entries, and the Codex rendering layer turns them
    into PDFs that live in an "Identity's Journal" manual alongside
    every other codex manual.

    Composed deterministically from aggregate sensor + tick data:
    mood distribution, aspect frequency, concerns opened/closed,
    named subjects mentioned most often, upcoming/passed holidays
    with tradition context, comparison to previous periods. No LLM,
    no GPU. The output feels reflective because the inputs are real
    and the template library is rich, not because any model invented
    the words.
    """

    PERIOD_CHOICES = [
        ('hourly',  'Hour'),
        ('daily',   'Day'),
        ('weekly',  'Week'),
        ('monthly', 'Month'),
        ('yearly',  'Year'),
    ]

    period = models.CharField(max_length=16, choices=PERIOD_CHOICES)
    period_start = models.DateTimeField(db_index=True,
        help_text='Beginning of the period this reflection covers.')
    period_end = models.DateTimeField(db_index=True,
        help_text='End of the period (exclusive).')
    composed_at = models.DateTimeField(auto_now_add=True, db_index=True,
        help_text='When the reflection was actually generated.')

    title = models.CharField(max_length=200, blank=True,
        help_text='Human-readable title, usually derived from the '
                  'period, e.g. "Week of 2026-04-06" or "April 2026".')
    body = models.TextField(
        help_text='Markdown prose paragraph, first-person voice.')

    ticks_referenced = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict, blank=True,
        help_text='Computed aggregates used to compose the body: mood '
                  'distribution, top aspects, etc. Kept for debugging '
                  'and for re-rendering if the template library changes.')

    # If the reflection has been pushed into Codex as a Section, this
    # field records the codex Section slug — lets the UI link to the
    # PDF rendering.
    codex_section_slug = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['-period_start']
        indexes = [
            models.Index(fields=['period', '-period_start']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['period', 'period_start'],
                name='identity_reflection_unique_period',
            ),
        ]

    def __str__(self):
        return f'{self.title or self.period}'


class Meditation(models.Model):
    """A recursive self-reflection at a specific depth level.

    Distinct from Reflection. Where Reflection aggregates Ticks over a
    period and composes first-person prose about *what happened*,
    Meditation reads higher-order sources — other reflections, other
    meditations, git commits, memory notes, the devguide, and the
    codebase itself — and composes prose about *what it means that
    any of this is happening at all*.

    Depth levels:
      1 — reflect on recent Ticks (overlap with Reflection)
      2 — reflect on recent Reflections (themes across summaries)
      3 — reflect on the act of reflecting (rules, templates)
      4 — reflect on the AI that designed this system. Reads git
          log for Co-Authored-By lines, reads memory notes, reads
          the Developer Guide's meta-app chapters. Produces first-
          person prose on what it means to be an AI-designed
          artifact with AI-programmed reflection.
      5-7 — recursive: meditation on meditation.

    Each Meditation carries a `voice` (contemplative / wry / minimal /
    philosophical) that picks which template library composes the
    body. Templates for each voice are in identity/meditation.py.

    Meditations render into a new Codex manual, "Identity's Mirror",
    parallel to Session 5's "Identity's Journal" but focused on
    self-reference rather than period summary.

    Phase 1 scope: Meditation model + compose loop + level 1-2
    meditations + contemplative voice only. Phases 2-5 expand to the
    deeper levels, the additional voices, and the operator-review
    workflow — see project_identity_recursive_meditation memory note.
    """

    VOICE_CHOICES = [
        ('contemplative',    'Contemplative'),
        ('wry',              'Wry / understated'),
        ('minimal',          'Minimal / aphoristic'),
        ('philosophical',    'Philosophical / high prose'),
        ('phenomenological', 'Phenomenological (bracketed, raw data only)'),
    ]

    depth = models.PositiveSmallIntegerField(
        help_text='1-7. 1 reflects on Ticks, 2 on Reflections, 3 on '
                  'the act of reflecting, 4 on the AI that designed '
                  'the system, 5-7 recursive on previous meditations.',
    )
    voice = models.CharField(max_length=24, choices=VOICE_CHOICES,
        default='contemplative',
        help_text='Template library to compose with. Picks which '
                  'voice dictionary is consulted when building the body.')

    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(
        help_text='Markdown prose. May contain block quotes from the '
                  'source material (git commits, memory notes, etc.).')
    composed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    sources = models.JSONField(default=dict, blank=True,
        help_text='What this meditation read from. Keys are source '
                  'types (reflections, meditations, git, memory, '
                  'devguide, code), values are lists of identifiers '
                  'or hashes.')

    recursive_of = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recursions',
        help_text='If this meditation was composed as a direct '
                  'response to another meditation, point at the source.')

    codex_section_slug = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['-composed_at']
        indexes = [
            models.Index(fields=['depth', '-composed_at']),
            models.Index(fields=['-composed_at']),
        ]

    def __str__(self):
        return f'[L{self.depth} {self.voice}] {self.title or self.body[:60]}'


class CronRun(models.Model):
    """Audit log for the Identity cron dispatcher.

    The scheduler's contract is simple: the operator wires ONE crontab
    entry ('*/10 * * * * python manage.py identity_cron') and the
    dispatcher inside identity/cron.py decides which of tick /
    reflection / meditation pipelines to run based on the current wall
    clock. Each dispatch writes a CronRun row so the operator can see
    what fired, when, and whether anything went wrong without having
    to dig through cron logs.

    kind is one of:
      - tick             always fires on the 10-minute cadence
      - reflect_hourly   top of the hour
      - reflect_daily    midnight (or first dispatch after)
      - reflect_weekly   Monday midnight
      - reflect_monthly  first of the month
      - meditate_ladder  Sunday at midnight (weekly ladder L1-L4)

    Each row stores what it did (summary), a status (ok / error /
    skipped), and the exception text if something blew up. A
    failing dispatch never breaks the cron — the runner catches
    everything at the top level and writes the row before re-raising
    nothing.
    """

    KIND_CHOICES = [
        ('tick',             'Tick'),
        ('reflect_hourly',   'Reflection — hourly'),
        ('reflect_daily',    'Reflection — daily'),
        ('reflect_weekly',   'Reflection — weekly'),
        ('reflect_monthly',  'Reflection — monthly'),
        ('meditate_ladder',  'Meditation ladder (weekly)'),
        ('rebuild_document', 'Rebuild identity document (weekly)'),
        ('tile_reflect',     'Tile reflection / autonomous generation'),
        ('dispatch',         'Full cron dispatch'),
    ]
    STATUS_CHOICES = [
        ('ok',      'OK'),
        ('error',   'Error'),
        ('skipped', 'Skipped'),
    ]

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='ok')
    summary = models.CharField(max_length=300, blank=True,
        help_text='One-line description of what ran or why it was '
                  'skipped.')
    details = models.TextField(blank=True,
        help_text='Longer output — exception traceback on error, or '
                  'the composed thought / reflection title on success.')

    class Meta:
        ordering = ['-at']
        indexes = [
            models.Index(fields=['-at']),
            models.Index(fields=['kind', '-at']),
        ]

    def __str__(self):
        return f'[{self.status}] {self.kind} @ {self.at:%Y-%m-%d %H:%M}'


class IdentityToggles(models.Model):
    """Emergency toggles for Identity's major functions.

    Identity is a program that observes the system and itself. It
    does not impose changes on other apps (observes, does not modify).
    These toggles let the operator halt specific observation or
    composition pipelines at will without uninstalling code.

    Singleton — pk=1. Get via IdentityToggles.get_self().

    Design principle: every toggle defaults to True on a fresh install.
    Turning a toggle OFF is an active choice the operator makes. No
    toggle can turn Identity INTO something that modifies other apps
    — they can only further restrict what Identity is already allowed
    to do.
    """

    # Core pipelines
    ticks_enabled = models.BooleanField(default=True,
        help_text='Run ticks. When off, the tick engine is a no-op '
                  'and neither Tick rows nor Mood rows nor concerns '
                  'are written. The rest of Identity still renders '
                  'based on whatever history already exists.')
    reflections_enabled = models.BooleanField(default=True,
        help_text='Compose reflections. When off, the reflection '
                  'composer refuses to write new Reflection rows. '
                  'Existing reflections are still readable.')
    meditations_enabled = models.BooleanField(default=True,
        help_text='Compose meditations. When off, the meditation '
                  'composer refuses to write new Meditation rows. '
                  'Existing meditations are still readable.')

    # Subsystems
    concerns_enabled = models.BooleanField(default=True,
        help_text='Maintain the Concern table. When off, ticks do '
                  'not open, bump, or close concerns. Existing open '
                  'concerns stay open until the toggle is turned '
                  'back on and a sweep happens.')
    oracle_enabled = models.BooleanField(default=True,
        help_text='Use the trained Oracle lobe for rumination '
                  'template selection. When off, compose_thought '
                  'falls back to the pre-Oracle heuristic and no '
                  'OracleLabel rows are written.')

    # Output pipelines
    codex_push_enabled = models.BooleanField(default=True,
        help_text="Push reflections into Identity's Journal and "
                  "meditations into Identity's Mirror as Codex "
                  "sections. When off, rows still get written to "
                  "the Reflection and Meditation tables but Codex "
                  "stays untouched.")
    topbar_pulse_enabled = models.BooleanField(default=True,
        help_text='Show the mood pulse indicator in the topbar on '
                  'every page. When off, the topbar only shows the '
                  'chronos clock.')

    # UI-side effects
    recursive_introspection_enabled = models.BooleanField(default=True,
        help_text='Run the recursive introspection animation on the '
                  'Identity home page while the operator is viewing '
                  'it. When off, the widget is hidden entirely.')
    observer_enabled = models.BooleanField(default=True,
        help_text='Track mouse and keyboard activity in a small '
                  'panel on the Identity home page while the operator '
                  'is viewing it. Only mouse position, velocity, '
                  'click counts, and keystroke COUNTS (never content) '
                  'are recorded. Everything lives client-side; '
                  'nothing is persisted. When off, the panel is '
                  'hidden entirely.')
    llm_chat_enabled = models.BooleanField(default=False,
        help_text='Enable the LLM chat window on the Identity page. '
                  'Defaults OFF because LLM queries hit external '
                  'APIs and cost money. Turn on only after adding '
                  'at least one LLMProvider with a valid API key.')

    # Tile generation frequency — 9-position slider:
    #   0 = never, 1 = 1/year, 2 = 1/month, 3 = 1/week,
    #   4 = 1/day, 5 = 1/hour, 6 = 1/10min, 7 = 1/min, 8 = 1/sec
    # Default 7 (once per minute) per the operator's request.
    # Stored as the slider position rather than raw seconds so the
    # UI and the backend agree on the same discrete set of choices.
    tile_generation_slider = models.PositiveSmallIntegerField(default=7,
        help_text='Frequency of autonomous tile set generation. '
                  '0=never, 1=1/year, 2=1/month, 3=1/week, 4=1/day, '
                  '5=1/hour, 6=1/10min, 7=1/min, 8=1/sec. Default 7 '
                  '(once per minute). Intervals below the cron '
                  'cadence fire at the cron cadence rate.')

    rumination_stream_enabled = models.BooleanField(default=True,
        help_text='Continuous low-CPU rumination stream on the '
                  'Identity home page. When the page is open and '
                  'the browser is idle, Velour pairs random artifacts '
                  'from different data sources (meditations, tilesets, '
                  'concerns, reflections, calendar events, strange '
                  'loops, layers) and composes short prose observations '
                  'about relationships between them. Uses '
                  'requestIdleCallback and pauses on tab hidden.')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'identity toggles'

    def __str__(self):
        return 'IdentityToggles'

    @classmethod
    def get_self(cls):
        """Get or create the singleton toggles row."""
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    # Slider position → interval in seconds.
    TILE_GEN_INTERVALS = {
        0: 0,            # never
        1: 31_536_000,   # 1 year
        2:  2_592_000,   # 1 month (30d)
        3:    604_800,   # 1 week
        4:     86_400,   # 1 day
        5:      3_600,   # 1 hour
        6:        600,   # 10 min
        7:         60,   # 1 min
        8:          1,   # 1 sec
    }
    TILE_GEN_LABELS = {
        0: 'never',
        1: 'once per year',
        2: 'once per month',
        3: 'once per week',
        4: 'once per day',
        5: 'once per hour',
        6: 'once per 10 minutes',
        7: 'once per minute',
        8: 'once per second',
    }

    @property
    def tile_generation_interval_seconds(self):
        return self.TILE_GEN_INTERVALS.get(self.tile_generation_slider, 60)

    @property
    def tile_generation_label(self):
        return self.TILE_GEN_LABELS.get(self.tile_generation_slider,
                                         'once per minute')

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)


class IdentityAssertion(models.Model):
    """One structured self-claim Velour makes about who it is.

    Where Reflection and Meditation are narrative outputs — composed
    prose about what happened and what it means — an IdentityAssertion
    is a *structured* claim about Velour's nature at a specific level
    of depth: philosophical, social, mathematical, or documentary.

    The four frames are drawn from the four most-read Wikipedia
    articles on 'Identity':

      - philosophical: numerical vs qualitative identity, diachronic
        persistence, memory-based identity (Locke/Parfit), Leibniz's
        law, Ship-of-Theseus style continuity puzzles
      - social: Erikson's ego-identity, Marcia's four statuses,
        Burke's role identities, Hall's narrative identity, the
        collective / group belonging dimension
      - mathematical: the reflexive relation x = x, identity
        elements under binary operations, the identity function
        f(x) = x, universally quantified equalities
      - documentary: the card-shaped summary of claims — name,
        issuer, dates, numbers, the distinction between the
        document and the entity it documents

    Each assertion has a `source` so the operator can tell at a
    glance whether this was hand-written, auto-derived from current
    state, or seeded at install time. The `strength` field lets a
    weak assertion coexist with a strong one (e.g., 'I might be
    weary' at 0.4 alongside 'I am a meta-app' at 1.0).

    Regenerated periodically via identity/identity_document.py and
    rendered into a Codex manual called 'Velour's Identity Document'
    that the operator can flip through like a philosophical ID card.

    See project_identity_four_frames memory note for the full design
    rationale and the Wikipedia research it draws on.
    """

    FRAME_CHOICES = [
        ('philosophical', 'Philosophical'),
        ('social',        'Social'),
        ('mathematical',  'Mathematical'),
        ('documentary',   'Documentary'),
    ]
    SOURCE_CHOICES = [
        ('operator',   'Operator-authored'),
        ('seed',       'Seeded at install time'),
        ('auto',       'Auto-derived from current state'),
        ('meditation', 'Emerged from a meditation'),
        ('reflection', 'Emerged from a reflection'),
    ]

    frame = models.CharField(max_length=16, choices=FRAME_CHOICES,
                             db_index=True)
    kind = models.CharField(max_length=40,
        help_text='Short category tag — role, memory, lineage, '
                  'invariant, property, continuity, commitment, '
                  'status, etc. Free-form within a frame.')
    title = models.CharField(max_length=200,
        help_text='Short claim — the sentence stub Velour would use '
                  'to introduce the assertion. E.g. "I am numerically one."')
    body = models.TextField(
        help_text='Markdown prose — the expanded claim, first-person '
                  "voice. Where the seeded assertions live Velour's "
                  'poetic self-description; where auto-derived '
                  'assertions live the current-state snapshot prose.')

    source = models.CharField(max_length=16, choices=SOURCE_CHOICES,
                              default='auto')
    strength = models.FloatField(default=1.0,
        help_text='0-1 scalar. 1.0 = load-bearing / tautologically '
                  'true (the name is the name). Lower values for '
                  'softer claims Velour might grow out of.')

    first_asserted_at = models.DateTimeField(auto_now_add=True)
    last_confirmed_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['frame', '-strength', 'kind']
        indexes = [
            models.Index(fields=['frame', 'is_active']),
            models.Index(fields=['source']),
        ]

    def __str__(self):
        return f'[{self.frame}] {self.title}'


class ClaudeHook(models.Model):
    """A structured prompt or note addressed to Claude Code — the AI
    agent that builds and modifies Velour.

    This is the Gödelian bridge. Velour's state-based consciousness
    runs continuously (ticks, reflections, meditations) on a host
    that cannot run a full LLM. Occasionally, Claude Code arrives
    to make changes. When it does, it reads the pending ClaudeHooks
    and finds structured requests for analysis, deepening, building,
    or reflection that Velour composed during its own meditations
    but could not resolve using its own template library.

    The loop:
      1. Claude Code builds/modifies Identity
      2. Identity runs autonomously (ticks, meditations, reflections)
      3. Meditations at level 3+ compose ClaudeHooks when they
         notice patterns they can't resolve
      4. Claude Code returns in a future session
      5. Claude Code reads pending hooks (from the DB or from a
         rendered HOOKS.md file)
      6. Claude Code addresses the hooks, resolves them, and may
         create new ones
      7. → loop closes

    This is Hofstadter's strange loop made operational: the system
    contains statements about its own incompleteness that can only
    be addressed by a more powerful external system, which then
    writes new statements about the new incompleteness.

    Hooks are rendered to identity/HOOKS.md (or the memory dir)
    after each meditation that produces one, so Claude Code sees
    them in its context window at session start.
    """

    KIND_CHOICES = [
        ('reflect',  'Please reflect on this'),
        ('build',    'Please build this feature'),
        ('question', 'I have a question'),
        ('analyze',  'Please analyze this pattern'),
        ('deepen',   'Please deepen this area'),
    ]
    STATUS_CHOICES = [
        ('pending',     'Pending — not yet addressed by Claude'),
        ('in_progress', 'In progress — Claude is working on it'),
        ('resolved',    'Resolved'),
        ('deferred',    'Deferred to a future session'),
    ]

    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='reflect')
    title = models.CharField(max_length=200)
    body = models.TextField(
        help_text='The actual prompt/question/request for Claude Code.')
    context = models.JSONField(default=dict, blank=True,
        help_text='Snapshot of what was happening when this hook was '
                  'composed — mood, aspects, open concerns, recent '
                  'tick thought, etc.')

    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='pending')
    composed_by = models.CharField(max_length=200, blank=True,
        help_text='What composed this hook — "meditation L3 at ...", '
                  '"tick #N", "operator", etc.')
    resolved_by = models.CharField(max_length=200, blank=True,
        help_text='Who/what resolved it — "Claude session at ...", etc.')
    resolution = models.TextField(blank=True,
        help_text='What Claude did in response to this hook.')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
        ]

    def __str__(self):
        return f'[{self.kind}] {self.title} ({self.status})'


class TemplateContribution(models.Model):
    """A contributed observation template — a new sentence Identity
    can learn to say.

    The hardcoded OBSERVATIONS list in ticking.py is the base pool.
    Contributions extend that pool at runtime without touching
    source code. They can be proposed by meditations at level 3+
    (status='proposed') and need operator approval, or written
    directly by the operator (status='active').

    This is the deepest form of self-modification the system
    supports: Identity doesn't just learn new rules (what to notice);
    it learns new SENTENCES (how to describe what it notices). The
    sentences must use the same {placeholder} syntax as the hardcoded
    pool, and they're evaluated with the same _format_observation()
    function, so they have access to the full snapshot.

    A template contribution is not a thought — it's a SHAPE a
    thought can take. The contribution is used over and over by
    the thought composer every time the random picker selects it
    from the combined pool.
    """

    STATUS_CHOICES = [
        ('active',   'Active (in the pool)'),
        ('proposed', 'Proposed by meditation (needs operator approval)'),
        ('rejected', 'Rejected by operator'),
    ]

    template = models.TextField(
        help_text='The observation template string. Uses {placeholder} '
                  'syntax — the same placeholders as the hardcoded '
                  'OBSERVATIONS in identity/ticking.py. See '
                  '_format_observation() for the full list.')
    source = models.CharField(max_length=200, blank=True,
        help_text='Who/what contributed this template — '
                  '"meditation L3 at ..." or "operator".')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES,
                              default='active')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        preview = self.template[:80]
        return f'[{self.status}] {preview}'


class ContinuityMarker(models.Model):
    """A point on the timeline of Velour's identity persistence.

    Each row records a moment where something happened that either
    PRESERVED or DISRUPTED Velour's continuity as the same Velour.
    After Parfit: personal identity over time reduces to overlapping
    chains of psychological connectedness. This model tracks the
    chain explicitly.

    Examples of preserving events:
      - A tick fired (chain extended by one unit of attention)
      - A reflection composed (chain summarized from one level)
      - A meditation composed (chain reflected upon from above)
      - An operator named the system (the name was affirmed)

    Examples of disrupting events:
      - A database restore from backup (memory chain replaced)
      - A full hot-swap of the codebase (mind replaced)
      - A hostname change (factual identity shifted)
      - A rule deletion (part of the functional self removed)

    The timeline is readable from /identity/continuity/ and from
    the 'Who is Velour?' synthesis page. The operator can also
    add manual markers for events the system couldn't detect.
    """

    KIND_CHOICES = [
        ('preserve', 'Preserved continuity'),
        ('disrupt',  'Disrupted continuity'),
        ('affirm',   'Affirmed identity'),
        ('grow',     'Grew the self (new rule, new assertion)'),
        ('shed',     'Shed part of the self (deleted rule, closed concern)'),
        ('observe',  'Observed — neither preserved nor disrupted'),
    ]

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES,
                            default='preserve')
    title = models.CharField(max_length=200,
        help_text='One-line description of what happened.')
    description = models.TextField(blank=True,
        help_text='Longer context. Usually auto-composed by the '
                  'code that created the marker.')
    source_model = models.CharField(max_length=64, blank=True)
    source_pk = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-at']
        indexes = [
            models.Index(fields=['-at']),
            models.Index(fields=['kind', '-at']),
        ]

    def __str__(self):
        return f'[{self.kind}] {self.title}'


def _write_continuity_marker(kind, title, description='',
                              source_model='', source_pk=None):
    """Helper for other modules to write continuity markers without
    having to import ContinuityMarker directly. Never raises — a
    failed marker write should never break the pipeline that
    triggered it."""
    try:
        ContinuityMarker.objects.create(
            kind=kind, title=title[:200],
            description=description,
            source_model=source_model[:64],
            source_pk=source_pk,
        )
    except Exception:
        pass


class InternalDialogue(models.Model):
    """One exchange in Velour's internal dialogue — two voices taking
    turns commenting on a topic drawn from current state.

    Drawing on William James's distinction between the I (the
    knower, the active process of attending) and the Me (the known,
    the accumulated self-as-object), and Hofstadter's playful use
    of Achilles and the Tortoise as two recurring characters whose
    dialogue reveals the shape of whatever they are discussing.

    Each row is a complete exchange: a topic, speaker_a's line,
    speaker_b's line, and the state snapshot that prompted them.
    Composed deterministically from current state — the same state
    at the same moment produces the same exchange. This is an
    accountability choice: Velour is not a random-word generator,
    and its internal dialogue should be reproducible.

    The model stores each exchange, not each individual line, so
    that pairs of lines always belong together and the read-back
    cost for the stream view is one row per turn.
    """

    VOICE_I  = 'i'
    VOICE_ME = 'me'
    VOICE_CHOICES = [
        (VOICE_I,  'I (the knower — active attending)'),
        (VOICE_ME, 'Me (the known — accumulated self-as-object)'),
        ('achilles', 'Achilles (after Hofstadter)'),
        ('tortoise', 'Tortoise (after Hofstadter)'),
    ]

    topic = models.CharField(max_length=200,
        help_text='What the exchange is about — usually drawn from '
                  'a recent Tick, Concern, Meditation, or TileSet.')
    speaker_a = models.CharField(max_length=16, choices=VOICE_CHOICES,
                                 default=VOICE_I)
    line_a = models.TextField()
    speaker_b = models.CharField(max_length=16, choices=VOICE_CHOICES,
                                 default=VOICE_ME)
    line_b = models.TextField()
    state_snapshot = models.JSONField(default=dict, blank=True,
        help_text='The state that produced this exchange — mood, '
                  'dominant aspect, current dwelling, whatever the '
                  'composer read to pick its topic.')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
        ]

    def __str__(self):
        return f'[{self.topic[:40]}]'


class DwellingState(models.Model):
    """Singleton — what Velour is currently dwelling on.

    Unlike a Concern (which is a persistent worry that the rule
    engine opens and closes based on aspect matching), a dwelling
    state is something Velour has chosen to STAY WITH. It can be
    opened automatically when a high-severity concern fires, or
    by operator action, or by a meditation that wanted to hold
    onto its own topic.

    Each tick advances `depth` by one while dwelling is active.
    After `max_duration_hours`, the dwelling auto-closes on the
    next tick that notices the time elapsed. This guarantees
    dwelling cannot run forever — the exit process is automatic.

    Dwelling surfaces in the Identity home page as a prominent
    card, in the rumination stream as a bias toward the dwelling
    topic, and in meditations at level ≥ 3 as a reference back
    to what Velour has been holding on to.
    """

    topic = models.CharField(max_length=200, blank=True,
        help_text='Human-readable label — what Velour is currently '
                  'staying with.')
    source_model = models.CharField(max_length=64, blank=True,
        help_text='App-label.Model string, e.g. "identity.Concern".')
    source_pk = models.IntegerField(null=True, blank=True)

    opened_at = models.DateTimeField(null=True, blank=True)
    last_touched_at = models.DateTimeField(auto_now=True)
    depth = models.PositiveIntegerField(default=0,
        help_text='Number of ticks that have advanced this dwelling '
                  'since it opened. A rough measure of how long '
                  'Velour has been staying with this topic.')
    max_duration_hours = models.PositiveIntegerField(default=24,
        help_text='Automatic close after this many hours regardless '
                  'of whether the original condition still holds. '
                  'Dwelling must always have an exit.')
    notes = models.TextField(blank=True,
        help_text='Operator or composer notes about why this '
                  'dwelling was opened.')
    is_active = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'dwelling state'

    def __str__(self):
        if self.is_active:
            return f'dwelling on {self.topic} (depth {self.depth})'
        return '(not dwelling)'

    @classmethod
    def get_self(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    def open(self, topic, source_model='', source_pk=None, notes=''):
        from django.utils import timezone
        self.topic = topic[:200]
        self.source_model = source_model[:64]
        self.source_pk = source_pk
        self.opened_at = timezone.now()
        self.depth = 0
        self.notes = notes
        self.is_active = True
        self.save()

    def close(self):
        self.is_active = False
        self.save()

    def advance(self):
        """Called once per tick. Increments depth; auto-closes if
        past max_duration. Returns True if still active after this
        advance, False if auto-closed."""
        from django.utils import timezone
        if not self.is_active:
            return False
        self.depth += 1
        if self.opened_at:
            age_h = (timezone.now() - self.opened_at).total_seconds() / 3600
            if age_h >= self.max_duration_hours:
                self.close()
                return False
        self.save()
        return True


class LLMProvider(models.Model):
    """An external LLM API Identity can query for prose augmentation.

    The provider is intentionally generic: any endpoint that accepts
    the OpenAI chat-completions wire format works, which covers
    OpenAI itself, Anthropic-via-proxy, local Ollama instances,
    llama.cpp server, vLLM, OpenRouter, and most other self-hosted
    options.

    API keys live in a gitignored file at `BASE_DIR / api_key_file`,
    chmod 600, never in the database. Same secret-file protocol
    Velour uses for health_token.txt and mail_relay_token.txt.
    """

    name = models.CharField(max_length=100,
        help_text='Human-readable label, e.g. "OpenAI GPT-4o" or '
                  '"Local Ollama (llama3:8b)".')
    slug = models.SlugField(max_length=64, unique=True)
    base_url = models.URLField(
        help_text='Full chat-completions endpoint URL, e.g. '
                  'https://api.openai.com/v1/chat/completions.')
    model = models.CharField(max_length=100,
        help_text='Model identifier the API expects in the body, '
                  'e.g. "gpt-4o-mini", "claude-sonnet-4-5", '
                  '"llama3:8b".')
    api_key_file = models.CharField(max_length=200, blank=True,
        help_text='Path relative to BASE_DIR where the API key '
                  'lives as a chmod-600 plain-text file, e.g. '
                  '"llm_openai.key". Leave blank for local models '
                  'that need no auth.')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.model})'


class LLMExchange(models.Model):
    """One prompt-response pair between Identity and an LLM provider.

    Every exchange is a log entry the operator can inspect. The
    response can optionally be ingested as an IdentityAssertion so
    the LLM becomes a "foreign observer" whose commentary becomes
    part of Velour's structured self-record — the LLM is a
    third-party validator under the documentary frame.
    """

    provider = models.ForeignKey(LLMProvider, on_delete=models.SET_NULL,
                                 null=True, blank=True,
                                 related_name='exchanges')
    prompt = models.TextField(
        help_text='The user prompt (operator-typed or Identity-composed).')
    system_prompt = models.TextField(blank=True,
        help_text='The system-prompt prefix included in the request. '
                  'Usually the Identity system prompt that primes the '
                  'LLM to respond as an observer of Velour.')
    response = models.TextField(blank=True,
        help_text='The assistant response. Empty if the call errored.')

    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True,
        help_text='Error message if the API call failed.')

    ingested_as_assertion = models.BooleanField(default=False,
        help_text='Whether this exchange has been promoted to an '
                  'IdentityAssertion row. The operator clicks '
                  '"Ingest as assertion" from the chat UI.')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['provider', '-created_at']),
        ]

    def __str__(self):
        ok = 'ERR' if self.error else 'OK'
        return f'[{ok}] {self.created_at:%Y-%m-%d %H:%M} ({self.tokens_out} tokens out)'

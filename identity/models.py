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

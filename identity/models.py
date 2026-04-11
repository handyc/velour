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
    """Historical mood log."""
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

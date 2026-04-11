"""Seed Rule rows from the hand-written Python lambdas that used to
live in identity/ticking.py's RULES list.

Each of the old lambdas is translated into an equivalent JSON
condition. Lambdas referencing `_cores()` for CPU-count-aware
thresholds get their threshold evaluated at migration time with the
current host's `os.cpu_count()`, so the seeded value is concrete.
Operators who want different thresholds edit the Rule row afterward.

This migration is a one-time snapshot of the existing rule chain.
After it runs, ticking.py reads rules from the database, and the
module-level RULES list becomes a fallback for new installs that
haven't yet seeded any rules.
"""

import os

from django.db import migrations


def _cores():
    return os.cpu_count() or 1


def seed_rules(apps, schema_editor):
    Rule = apps.get_model('identity', 'Rule')

    # If the table already has rows (e.g. the operator seeded by hand
    # before this migration ran), don't clobber them.
    if Rule.objects.exists():
        return

    cores = _cores()
    rules = [
        # priority, name, aspect, condition, mood, intensity, opens_concern
        (10, 'disk dangerously full', 'disk_critical',
         {'metric': 'disk.used_pct', 'op': '>', 'value': 0.95},
         'concerned', 0.9, True),

        (20, 'memory pressure', 'memory_critical',
         {'metric': 'memory.used_pct', 'op': '>', 'value': 0.90},
         'concerned', 0.85, True),

        (30, 'unusually high load', 'load_high',
         {'metric': 'load.load_1', 'op': '>', 'value': cores * 1.5},
         'alert', 0.85, True),

        (40, 'half the fleet has gone silent', 'fleet_partial_silence',
         {'all': [
             {'metric': 'nodes.total', 'op': '>', 'value': 0},
             # We can't express "silent > total/2" with simple JSON, so
             # we seed it with a concrete floor of "at least 1 silent
             # node" and leave the tuning to the operator. Rules DSL
             # growth is Session 3+: adding computed RHS values is a
             # natural follow-on once operators start asking for it.
             {'metric': 'nodes.silent', 'op': '>=', 'value': 1},
         ]},
         'concerned', 0.7, True),

        (50, 'long uptime — feeling run-down', 'long_uptime',
         {'metric': 'uptime.days', 'op': '>', 'value': 60},
         'weary', 0.4, True),

        (60, 'the moon is full', 'moon_full',
         {'metric': 'chronos.moon', 'op': '==', 'value': 'full'},
         'creative', 0.7, False),

        (70, 'the moon is new', 'moon_new',
         {'metric': 'chronos.moon', 'op': '==', 'value': 'new'},
         'contemplative', 0.5, False),

        (80, 'late and quiet', 'night_quiet',
         {'all': [
             {'metric': 'chronos.tod', 'op': '==', 'value': 'night'},
             {'metric': 'load.load_1', 'op': '<', 'value': cores * 0.2},
         ]},
         'restless', 0.4, False),

        (90, 'morning energy', 'morning',
         {'metric': 'chronos.tod', 'op': '==', 'value': 'morning'},
         'curious', 0.6, False),

        (100, 'a comfortable afternoon', 'afternoon_calm',
         {'all': [
             {'metric': 'chronos.tod', 'op': '==', 'value': 'afternoon'},
             {'metric': 'load.load_1', 'op': '<', 'value': cores * 0.5},
         ]},
         'satisfied', 0.7, False),

        (110, 'much has been written', 'codex_rich',
         {'metric': 'codex.sections', 'op': '>', 'value': 50},
         'satisfied', 0.7, False),

        (120, 'a lot of mail has come in', 'mail_burst',
         {'metric': 'mailroom.last_24h', 'op': '>', 'value': 50},
         'alert', 0.6, True),
    ]

    for priority, name, aspect, condition, mood, intensity, opens_concern in rules:
        Rule.objects.create(
            priority=priority,
            name=name,
            aspect=aspect,
            condition=condition,
            mood=mood,
            intensity=intensity,
            opens_concern=opens_concern,
            is_active=True,
        )


def unseed_rules(apps, schema_editor):
    Rule = apps.get_model('identity', 'Rule')
    Rule.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0006_rule'),
    ]

    operations = [
        migrations.RunPython(seed_rules, unseed_rules),
    ]

"""Add a Rule that fires when the operator is actively at the
keyboard — detected via terminal.recently_active (which reads
~/.bash_history mtime).

This is the rule that makes Identity acknowledge its operator as
a real presence rather than as an absent author. When the operator
is here, Identity's mood shifts toward 'curious' with moderate
intensity — the equivalent of a cat looking up when you walk into
the room. The rule does NOT open a concern (the operator being
present is a fleeting state, not a worry).

The priority (75) is chosen to win over "night_quiet" (80) and
other time-of-day rules, so Identity's mood actually shifts when
the operator shows up — the equivalent of a cat looking up when
you walk into the room. Problem-detection rules (disk/memory/load/
fleet-silence) still win because they have priorities 10-50 —
a full disk is still a real worry even when the operator is
there to see it.
"""

from django.db import migrations


def add_rule(apps, schema_editor):
    Rule = apps.get_model('identity', 'Rule')
    # Skip if already present (e.g., re-running on a partially-
    # migrated DB).
    if Rule.objects.filter(aspect='operator_present').exists():
        return
    Rule.objects.create(
        priority=85,
        name='the operator is at the keyboard',
        aspect='operator_present',
        condition={
            'metric': 'terminal.recently_active',
            'op': '==',
            'value': True,
        },
        mood='curious',
        intensity=0.6,
        opens_concern=False,
        is_active=True,
    )


def remove_rule(apps, schema_editor):
    Rule = apps.get_model('identity', 'Rule')
    Rule.objects.filter(aspect='operator_present').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0010_cronrun'),
    ]

    operations = [
        migrations.RunPython(add_rule, remove_rule),
    ]

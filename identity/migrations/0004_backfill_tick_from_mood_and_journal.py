"""Backfill Tick rows from the legacy Mood + Identity.journal pair.

Before this migration, Identity's structured memory was split awkwardly
between the Mood table (one row per tick, with mood + intensity + a
trigger label) and the journal TextField (one timestamped first-person
line per tick, in free-form text). This migration joins them on
timestamp to produce Tick rows that carry both the structured fields
and the poetic first-person thought, so the rest of Session 1 can
drop the journal-as-string pattern without losing history.

The join is intentionally loose — Mood timestamps and journal-line
timestamps are often within a few seconds of each other but not
identical (the journal append happens after the Mood row is created,
and wall-clock resolution differs by platform). We pair them on
minute-precision by default and fall back to "orphan" rows on either
side if nothing matches. That's fine: historical Ticks with no
structured fields still get written, and Ticks with no matching
journal line just have an empty thought.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Identity = apps.get_model('identity', 'Identity')
    Mood = apps.get_model('identity', 'Mood')
    Tick = apps.get_model('identity', 'Tick')

    # Start from zero — if we're re-running on a partially-migrated DB,
    # blow away any existing Tick rows first. This migration is the
    # only code writing to Tick at this point, so that's safe.
    Tick.objects.all().delete()

    # Pull journal lines out of the Identity singleton, if any.
    journal_entries = []
    try:
        identity = Identity.objects.get(pk=1)
    except Identity.DoesNotExist:
        identity = None
    if identity and identity.journal:
        for line in identity.journal.strip().split('\n'):
            line = line.strip()
            if line.startswith('[') and ']' in line:
                ts_end = line.index(']')
                ts = line[1:ts_end]
                text = line[ts_end + 1:].strip()
                # Normalize the timestamp into a 'YYYY-MM-DD HH:MM' key
                # for minute-precision matching against Mood rows.
                key = ts[:16] if len(ts) >= 16 else ts
                journal_entries.append((key, text))

    # Index journal lines by minute-precision key. A minute may have
    # multiple entries if ticks fired in quick succession; we just
    # concatenate them so nothing is lost.
    journal_by_minute = {}
    for key, text in journal_entries:
        journal_by_minute.setdefault(key, []).append(text)

    # Walk Mood rows oldest-first so Tick.at (auto_now_add in the
    # forward direction) lines up sensibly if re-ordered.
    for mood_row in Mood.objects.order_by('timestamp'):
        minute_key = mood_row.timestamp.strftime('%Y-%m-%d %H:%M')
        matching_lines = journal_by_minute.get(minute_key, [])
        thought = ' / '.join(matching_lines) if matching_lines else ''

        Tick.objects.create(
            at=mood_row.timestamp,
            triggered_by='cron',  # historical rows — best guess
            mood=mood_row.mood,
            mood_intensity=mood_row.intensity,
            rule_label=mood_row.trigger or '',
            thought=thought,
            snapshot={},  # historical rows have no preserved snapshot
            aspects=[],
        )

    # Any journal entries that didn't pair with a Mood row become
    # orphan Ticks — mood is unknown so we use the singleton's current
    # mood as a fallback. These are rare (requires the journal to have
    # had an append without a corresponding Mood write, which only
    # happened in very early sessions).
    matched_keys = set()
    for mood_row in Mood.objects.all():
        matched_keys.add(mood_row.timestamp.strftime('%Y-%m-%d %H:%M'))
    fallback_mood = (identity.mood if identity else 'contemplative')
    for key, lines in journal_by_minute.items():
        if key in matched_keys:
            continue
        for text in lines:
            # Best-effort: parse 'YYYY-MM-DD HH:MM' back into a datetime.
            from datetime import datetime
            try:
                dt = datetime.strptime(key, '%Y-%m-%d %H:%M')
                from django.utils import timezone
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(
                        dt, timezone.get_current_timezone())
            except ValueError:
                continue
            Tick.objects.create(
                at=dt,
                triggered_by='cron',
                mood=fallback_mood,
                mood_intensity=0.5,
                rule_label='backfilled from orphan journal line',
                thought=text,
                snapshot={},
                aspects=[],
            )


def unbackfill(apps, schema_editor):
    # Reverse migration: just drop all Ticks. The source data (Mood +
    # Identity.journal) is untouched so we lose nothing.
    Tick = apps.get_model('identity', 'Tick')
    Tick.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0003_tick'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]

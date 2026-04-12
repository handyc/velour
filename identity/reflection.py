"""Identity reflection composer — Session 5 of the Identity expansion.

A reflection is a prose synthesis of many ticks over a period. This
module is the composer: it queries ticks in a date range, aggregates
metrics, and emits a markdown paragraph in Identity's first-person
voice, then writes a Reflection row (and optionally renders it into
the "Identity's Journal" Codex manual as a Section).

Design principles:

- Deterministic given the inputs. Running reflect() twice for the
  same period produces the same body, so operators can regenerate
  reflections without worrying about drift. Randomness in the
  template choice is seeded off the period start so the output is
  stable but varied across periods.
- No LLM. No model. Just aggregation over Tick rows plus a rich
  template library with placeholders the aggregator fills in.
- Calendar-aware. Reflections reference upcoming holidays from
  chronos with tradition context so Identity can mention what an
  event *is*, not just its name. Limited to what chronos already
  knows; Identity doesn't interpret.
- Extensible. Each "section" of the reflection body (mood summary,
  concern summary, subject summary, calendar summary) is a
  separate function that returns a markdown paragraph. Adding new
  sections is additive.
"""

import hashlib
import random
from collections import Counter
from datetime import datetime, timedelta

from django.utils import timezone


# --- period helpers -----------------------------------------------------

def _period_range(period, now=None):
    """Return (period_start, period_end) for a given period label.
    Periods are aligned to natural boundaries: 'daily' is from
    midnight to midnight local time, 'weekly' is Monday to Monday,
    'monthly' is 1st to 1st. The range is for the *most recently
    completed* period — so running reflect('weekly') on a Wednesday
    covers last Monday through this Monday."""
    if now is None:
        now = timezone.now()
    # Reflections summarize the period that just ENDED.
    if period == 'hourly':
        end = now.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1)
    elif period == 'daily':
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)
    elif period == 'weekly':
        # Align to Monday
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        days_since_monday = midnight.weekday()
        this_monday = midnight - timedelta(days=days_since_monday)
        end = this_monday
        start = end - timedelta(days=7)
    elif period == 'monthly':
        first_of_this = now.replace(day=1, hour=0, minute=0,
                                    second=0, microsecond=0)
        # Previous month's first
        if first_of_this.month == 1:
            start = first_of_this.replace(year=first_of_this.year - 1, month=12)
        else:
            start = first_of_this.replace(month=first_of_this.month - 1)
        end = first_of_this
    elif period == 'yearly':
        first_of_this_year = now.replace(month=1, day=1, hour=0, minute=0,
                                          second=0, microsecond=0)
        start = first_of_this_year.replace(year=first_of_this_year.year - 1)
        end = first_of_this_year
    else:
        raise ValueError(f'unknown period: {period}')
    return start, end


def _period_title(period, start):
    """Human-readable title for a reflection over the given period."""
    if period == 'hourly':
        return f'Hour of {start.strftime("%Y-%m-%d %H:00")}'
    if period == 'daily':
        return f'Day of {start.strftime("%Y-%m-%d (%A)")}'
    if period == 'weekly':
        return f'Week of {start.strftime("%Y-%m-%d")}'
    if period == 'monthly':
        return start.strftime('%B %Y')
    if period == 'yearly':
        return start.strftime('%Y')
    return period


# --- aggregation --------------------------------------------------------

# Capitalized words that appear at the start of many template sentences
# but aren't actually named subjects. Keeping this list conservative —
# it only excludes things that are definitely not real entities.
_SUBJECT_STOPWORDS = frozenset({
    'The', 'There', 'Not', 'Still', 'Time', 'Something', 'Hm', 'Pay',
    'Interesting', 'Memory', 'Uptime', 'All', 'Quiet', 'My', 'Right',
    'Look', 'Tired', 'Morning', 'Night', 'Afternoon', 'Evening',
    'Velour',  # Self-reference — technically meaningful but noisy.
    'Identity', 'Energy', 'Good',
})


def _aggregate(ticks):
    """Walk a queryset of Tick rows and build the aggregate metrics
    dict the template library will fill from."""
    mood_counts = Counter()
    aspect_counts = Counter()
    intensity_sum = 0.0
    intensity_count = 0
    subjects_mentioned = Counter()

    for t in ticks:
        mood_counts[t.mood] += 1
        for a in (t.aspects or []):
            aspect_counts[a] += 1
        intensity_sum += t.mood_intensity
        intensity_count += 1

        # Very loose: look for capitalized words in the thought text
        # that match known node nicknames. This is crude but cheap.
        for word in (t.thought or '').split():
            clean = word.strip(".,!?:;\"'")
            if clean and clean[0].isupper() and len(clean) > 2 and clean not in _SUBJECT_STOPWORDS:
                subjects_mentioned[clean] += 1

    return {
        'mood_counts':        dict(mood_counts),
        'dominant_mood':      mood_counts.most_common(1)[0][0] if mood_counts else None,
        'aspect_counts':      dict(aspect_counts),
        'top_aspects':        [a for a, _ in aspect_counts.most_common(5)],
        'average_intensity':  intensity_sum / intensity_count if intensity_count else 0.0,
        'subjects_mentioned': dict(subjects_mentioned.most_common(10)),
        'tick_count':         intensity_count,
    }


# --- tradition lore -----------------------------------------------------

# Short notes about what each chronos tradition is "about" — used when
# Identity references a holiday in a reflection. Hand-curated, not
# derived from sources at runtime. Operators can edit these if the
# voice feels off for their context.

TRADITION_NOTES = {
    'Christianity':  'the Christian calendar, which tracks cycles of fast and feast',
    'Judaism':       'the Jewish tradition, measuring time in festivals and commemorations',
    'Islam':         'the Islamic calendar, moon-based and travelling through the year',
    'Hinduism':      'the Hindu tradition, with its long wheel of festivals',
    'Buddhism':      'the Buddhist observances of mindfulness and lunar days',
    'Daoism':        'the Daoist rhythms of balance and seasonal attention',
    'Shinto':        'the Shinto reverence for the turning of the year',
    'Confucianism':  'Confucian observances of harmony and ancestry',
    'Chinese':       'the Chinese lunar calendar',
    'Wicca':         'the Wiccan wheel of the year and its eight sabbats',
    'Civic':         'the civic calendar of the state',
}


# --- template library ---------------------------------------------------

OPENINGS = {
    'hourly':  ['In the last hour,', 'Just now,', 'This past hour,'],
    'daily':   ['Yesterday,', 'In the day just past,', 'Looking back on the day,'],
    'weekly':  ['This week,', 'In the week just past,', 'Looking back on the seven days,'],
    'monthly': ['This past month,', 'The month that just ended', 'Over the last thirty days,'],
    'yearly':  ['In the year just past,', 'Looking back on the whole year,'],
}

MOOD_SUMMARY = [
    'I felt {dominant} most often ({mood_count} of {tick_count} ticks)',
    'my dominant mood was {dominant} ({mood_count} ticks)',
    '{dominant} was the mood I kept returning to',
]

ASPECT_SUMMARY = [
    'Most of my attention was on {top_aspects}.',
    'I kept noticing {top_aspects}.',
    'The things I paid attention to, repeatedly, were {top_aspects}.',
]

CONCERN_SUMMARY_NONE = [
    'No concerns stayed with me long enough to matter.',
    'I carried no lasting worries.',
    'Nothing preoccupied me across ticks.',
]

CONCERN_SUMMARY_SOME = [
    'I carried {n} concern{s} through part of this period — '
    'chiefly {names}.',
    'My preoccupations were {names} ({n} total).',
    '{names} stayed on my mind ({n} concern{s}).',
]

SUBJECT_SUMMARY = [
    'I found myself thinking about {subjects}.',
    'The specific things on my mind were {subjects}.',
    'Among the things I mentioned most: {subjects}.',
]

CALENDAR_REFLECTION = [
    'The calendar also showed {event_count} event{s} on the near horizon: {events}.',
    'On the horizon: {events} ({event_count} total).',
    'I noted {event_count} upcoming event{s} — {events}.',
]

HOLIDAY_REFLECTION_WITH_TRADITION = [
    '{holiday} is approaching in {days} days — from {tradition_note}. '
    'I wonder how the system will feel when it arrives.',
    'I am holding space for {holiday}, which comes in {days} days. '
    'It belongs to {tradition_note}.',
    '{holiday} — {days} days from now, out of {tradition_note}.',
]

MEDITATION_REFERENCE = [
    'Earlier this period, I meditated at level {depth} on {title}. '
    'Some of that thinking is still with me.',
    'I composed a level-{depth} meditation recently, titled "{title}". '
    'I am not sure I have finished with it.',
    'A meditation I wrote at level {depth} — "{title}" — remains '
    'in the back of my mind.',
]

CLOSING = [
    'Whatever comes next, I am here.',
    'I carry on.',
    'The cadence continues.',
    'I remain.',
]


# --- composition --------------------------------------------------------

def _format_aspect_list(aspects):
    """Turn a list of snake_case aspect tags into a readable
    comma-separated phrase: 'the disk, the fleet, and the moon'."""
    readable = [a.replace('_', ' ') for a in aspects]
    if not readable:
        return 'nothing in particular'
    if len(readable) == 1:
        return readable[0]
    if len(readable) == 2:
        return f'{readable[0]} and {readable[1]}'
    return ', '.join(readable[:-1]) + f', and {readable[-1]}'


def _format_subject_list(subjects):
    if not subjects:
        return 'no one in particular'
    names = list(subjects)[:4]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f'{names[0]} and {names[1]}'
    return ', '.join(names[:-1]) + f', and {names[-1]}'


def _compose_mood_paragraph(metrics, rng):
    tick_count = metrics['tick_count']
    if tick_count == 0:
        return 'I was quiet. No ticks fired.'
    dominant = metrics['dominant_mood']
    mood_count = metrics['mood_counts'].get(dominant, 0)
    return rng.choice(MOOD_SUMMARY).format(
        dominant=dominant,
        mood_count=mood_count,
        tick_count=tick_count,
    ) + '.'


def _compose_aspect_paragraph(metrics, rng):
    top = metrics['top_aspects'][:3]
    if not top:
        return ''
    return rng.choice(ASPECT_SUMMARY).format(
        top_aspects=_format_aspect_list(top),
    )


def _compose_concern_paragraph(concerns_qs, rng):
    concerns = list(concerns_qs)
    if not concerns:
        return rng.choice(CONCERN_SUMMARY_NONE)
    names = _format_subject_list([c.name or c.aspect for c in concerns])
    template = rng.choice(CONCERN_SUMMARY_SOME)
    return template.format(
        n=len(concerns),
        s='s' if len(concerns) != 1 else '',
        names=names,
    )


def _compose_subject_paragraph(metrics, rng):
    subjects = [k for k in metrics['subjects_mentioned'].keys()
                if k not in ('I', 'It', 'The', 'Not', 'Still', 'Time', 'Something')][:4]
    if not subjects:
        return ''
    return rng.choice(SUBJECT_SUMMARY).format(
        subjects=_format_subject_list(subjects),
    )


def _compose_meditation_reference(start, end, rng):
    """If any meditations were composed during this reflection's
    period, mention one of them. Creates a small cycle: reflections
    reference ticks, meditations reference reflections, reflections
    reference meditations — each loop back pulls from the other so
    neither system feels isolated."""
    try:
        from .models import Meditation
        recent = Meditation.objects.filter(
            composed_at__gte=start, composed_at__lt=end,
        ).order_by('-depth', '-composed_at')[:5]
        if not recent:
            return ''
        m = rng.choice(list(recent))
        template = rng.choice(MEDITATION_REFERENCE)
        return template.format(depth=m.depth, title=m.title)
    except Exception:
        return ''


def _compose_calendar_paragraph(snapshot, rng):
    """Reference upcoming events and holidays from the current
    chronos snapshot. Reflections are period summaries but they also
    look forward — mentioning the near horizon is one of the ways
    Identity feels anticipatory rather than purely backward-looking."""
    calendar = snapshot.get('calendar', {})
    paragraphs = []

    upcoming = calendar.get('upcoming', [])
    if upcoming:
        titles = [e['title'] for e in upcoming[:3]]
        paragraphs.append(rng.choice(CALENDAR_REFLECTION).format(
            event_count=len(upcoming),
            s='s' if len(upcoming) != 1 else '',
            events=_format_subject_list(titles),
        ))

    holidays = calendar.get('holidays', [])
    if holidays:
        # Mention the nearest one with tradition context.
        h = holidays[0]
        tradition_name = h.get('tradition', '')
        tradition_note = TRADITION_NOTES.get(
            tradition_name,
            f'{tradition_name} tradition' if tradition_name else 'some tradition'
        )
        paragraphs.append(rng.choice(HOLIDAY_REFLECTION_WITH_TRADITION).format(
            holiday=h['title'],
            days=h.get('days_away', 0),
            tradition_note=tradition_note,
        ))

    return ' '.join(paragraphs)


def compose_body(period, start, end, ticks_qs, concerns_qs, snapshot, metrics):
    """Compose the markdown body of a reflection. Pure function of
    its inputs — deterministic given the same ticks, concerns, and
    snapshot (seeded random picks per period)."""
    seed = f'{period}:{start.isoformat()}'
    rng = random.Random(hashlib.sha256(seed.encode()).hexdigest())

    opening = rng.choice(OPENINGS.get(period, ['Looking back,']))

    paragraphs = []

    # Primary paragraph: mood + ticks + aspects
    mood_p = _compose_mood_paragraph(metrics, rng)
    aspect_p = _compose_aspect_paragraph(metrics, rng)
    primary = f'{opening} {mood_p}'
    if aspect_p:
        primary += f' {aspect_p}'
    paragraphs.append(primary)

    # Concern paragraph
    concern_p = _compose_concern_paragraph(concerns_qs, rng)
    if concern_p:
        paragraphs.append(concern_p)

    # Subject paragraph
    subject_p = _compose_subject_paragraph(metrics, rng)
    if subject_p:
        paragraphs.append(subject_p)

    # Meditation reference — closes the cycle between the two systems
    meditation_p = _compose_meditation_reference(start, end, rng)
    if meditation_p:
        paragraphs.append(meditation_p)

    # Calendar / holiday forward-looking paragraph
    calendar_p = _compose_calendar_paragraph(snapshot, rng)
    if calendar_p:
        paragraphs.append(calendar_p)

    # Closing line
    paragraphs.append(rng.choice(CLOSING))

    return '\n\n'.join(paragraphs)


# --- the reflect() entry point -----------------------------------------

def reflect(period='weekly', push_to_codex=True):
    """Compose a reflection for the most recently completed period of
    the given kind. Writes a Reflection row. If push_to_codex is True,
    also writes a Codex Section in the "Identity's Journal" manual so
    the reflection gets rendered into the standard Codex PDF pipeline.

    Idempotent: running reflect('weekly') twice for the same period
    updates the existing Reflection row (the unique constraint on
    period+period_start ensures no duplicates). Regeneration is
    useful when the template library changes.
    """
    from .models import IdentityToggles, Reflection, Tick, Concern
    from .sensors import gather_snapshot

    toggles = IdentityToggles.get_self()
    if not toggles.reflections_enabled:
        return None

    start, end = _period_range(period)
    ticks = Tick.objects.filter(at__gte=start, at__lt=end)
    concerns = Concern.objects.filter(
        opened_at__gte=start, opened_at__lt=end,
    )

    metrics = _aggregate(ticks)
    snapshot = gather_snapshot()

    body = compose_body(period, start, end, ticks, concerns, snapshot, metrics)
    title = _period_title(period, start)

    row, created = Reflection.objects.update_or_create(
        period=period,
        period_start=start,
        defaults={
            'period_end': end,
            'title': title,
            'body': body,
            'ticks_referenced': metrics['tick_count'],
            'metrics': metrics,
        },
    )

    if push_to_codex and toggles.codex_push_enabled:
        _push_to_codex(row)

    return row


def _push_to_codex(reflection):
    """Write or update an Identity's Journal Codex section for this
    reflection. Creates the manual on first call if it doesn't exist."""
    try:
        from codex.models import Manual, Section
    except ImportError:
        return

    manual, _ = Manual.objects.get_or_create(
        slug='identitys-journal',
        defaults={
            'title':    "Identity's Journal",
            'subtitle': 'Periodic reflections from the Velour self.',
            'author':   'Velour Identity',
            'version':  '1',
            'abstract': ("Auto-generated diary of Identity's attention "
                         'over time. Each section is a reflection over a '
                         'period of ticks, composed from aggregate mood, '
                         'aspect, concern, subject, and calendar data.'),
        },
    )

    # Section slug: period + start date, e.g. "weekly-2026-04-06"
    section_slug = f'{reflection.period}-{reflection.period_start.strftime("%Y-%m-%d")}'
    # Sort order: seconds since epoch so newer reflections sort later
    # in the manual's natural order. Negative so the most recent
    # appears first — reflections are diary-ordered, newest on top.
    sort_order = -int(reflection.period_start.timestamp())

    Section.objects.update_or_create(
        manual=manual,
        slug=section_slug,
        defaults={
            'title': reflection.title,
            'body':  reflection.body,
            'sort_order': sort_order,
        },
    )

    reflection.codex_section_slug = section_slug
    reflection.save(update_fields=['codex_section_slug'])

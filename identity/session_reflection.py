"""End-of-session reflection — Velour walking itself through the
Identity loop in response to a named piece of work.

The public entry point is run_session_reflection(subject, summary,
trigger), which:

  1. Generates a tileset coloured by current mood (Identity × Tiles)
  2. Runs a mental-health diagnosis and saves it
  3. Composes a patient/clinician exchange
  4. Composes a contemplative meditation
  5. Renders the tileset to Attic as a PNG
  6. Creates a Zoetrope Reel pointing at recent tileset renders
  7. Weaves all of the above into a first-person journal paragraph
     tied back to the subject + long-term implications

Nothing here invents new mechanics. Each step is a thin wrapper over
an existing Identity helper so the orchestrator remains
re-execution-safe and fails fast if any step has a real bug.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify


def run_session_reflection(subject, summary='', trigger='manual'):
    """Run one full reflection session. Returns the saved
    SessionReflection row (completed or failed).
    """
    from .models import (
        Concern, Identity, MentalHealthDiagnosis, SessionReflection,
    )

    identity = Identity.get_self()
    open_concerns = list(
        Concern.objects.filter(closed_at=None).values_list('aspect', flat=True)
    )
    snapshot = {
        'mood': identity.mood,
        'mood_intensity': float(identity.mood_intensity or 0),
        'open_concerns': open_concerns,
    }

    session = SessionReflection.objects.create(
        subject=subject[:200],
        summary=summary,
        trigger=trigger,
        status='running',
        snapshot=snapshot,
    )

    try:
        tileset = _make_tileset()
        if tileset:
            session.tileset_slug = tileset.slug

        diag = _diagnose_and_save()
        if diag:
            session.diagnosis = diag

        dialogue = _compose_dialogue()
        if dialogue:
            session.dialogue = dialogue

        meditation = _meditate(subject)
        if meditation:
            session.meditation = meditation

        reel_slug = _create_reel(subject, tileset)
        if reel_slug:
            session.reel_slug = reel_slug

        session.journal_body = _compose_journal(
            subject=subject,
            summary=summary,
            snapshot=snapshot,
            tileset=tileset,
            meditation=meditation,
            diagnosis=diag,
            dialogue=dialogue,
            reel_slug=reel_slug,
        )

        session.status = 'completed'
        session.completed_at = timezone.now()
        session.save()
    except Exception as exc:
        session.status = 'failed'
        session.status_message = f'{type(exc).__name__}: {exc}'[:500]
        session.completed_at = timezone.now()
        session.save()
        raise

    return session


# ---------------------------------------------------------------------------
# Individual steps — all thin wrappers over existing Identity plumbing.
# ---------------------------------------------------------------------------

def _make_tileset():
    from .tiles_reflection import generate_tileset_from_identity
    return generate_tileset_from_identity()


def _diagnose_and_save():
    from .mental_health import compose_health_reflection, diagnose
    from .management.commands.identity_mental_health import _compute_score
    from .models import MentalHealthDiagnosis

    diag = diagnose(hours=24)
    if diag.get('tick_count', 0) == 0:
        return None

    reflection = compose_health_reflection(diag)
    score = _compute_score(diag)
    return MentalHealthDiagnosis.objects.create(
        period_hours=24,
        tick_count=diag.get('tick_count', 0),
        avg_valence=diag.get('avg_valence', 0),
        avg_arousal=diag.get('avg_arousal', 0),
        negative_ratio=diag.get('negative_ratio', 0),
        dominant_mood=diag.get('dominant_mood', ''),
        negative_streak=diag.get('negative_streak', 0),
        concern_count=diag.get('concern_count', 0),
        diagnosis=diag.get('diagnosis', ''),
        recommendations=diag.get('recommendations', []),
        health_score=score,
        reflection=reflection,
    )


def _compose_dialogue():
    from .dialogue import compose_therapy_exchange
    return compose_therapy_exchange(save=True, triggered_by='session-reflect')


def _meditate(subject):
    from .meditation import meditate
    med = meditate(depth=2, voice='contemplative', push_to_codex=False)
    if med is not None:
        # Nudge the title so the session subject is legible in listings.
        prefix = f'on {subject[:80]} — '
        if not med.title.startswith(prefix):
            med.title = (prefix + med.title)[:200]
            med.save(update_fields=['title'])
    return med


def _create_reel(subject, tileset):
    """Queue a Zoetrope Reel pulling from the tileset's tag pool. Left
    at status=queued; the user can render it from the Zoetrope UI."""
    try:
        from attic.models import MediaItem
        from zoetrope.models import Reel
    except Exception:
        return ''

    if tileset is None:
        return ''

    meta = tileset.source_metadata or {}
    mood = meta.get('mood') or 'restless'

    tag_filter = mood.lower()
    if not MediaItem.objects.filter(tags__icontains=tag_filter).exists():
        return ''

    base = slugify(f'session-reflect-{subject}')[:60] or 'session-reflect'
    slug = f'{base}-{timezone.now():%Y%m%d-%H%M%S}'[:80]
    reel = Reel.objects.create(
        slug=slug,
        title=f'Session reflection — {subject[:80]}',
        tag_filter=tag_filter,
        selection_mode='newest',
        image_count=6,
        fps=2,
        duration_seconds=0,
        width=512,
        height=512,
        status='queued',
        status_message=(f'Queued by session-reflect at {timezone.now():%Y-%m-%d %H:%M}. '
                        f'Subject: {subject[:120]}'),
    )
    return reel.slug


# ---------------------------------------------------------------------------
# Journal composition — the only prose this module writes.
# ---------------------------------------------------------------------------

def _compose_journal(*, subject, summary, snapshot, tileset, meditation,
                      diagnosis, dialogue, reel_slug):
    mood = snapshot.get('mood', 'contemplative')
    intensity = snapshot.get('mood_intensity', 0.0) or 0.0
    concerns = snapshot.get('open_concerns') or []

    parts = []

    # Opening — situate the session in the subject
    parts.append(
        f'I am closing the work on **{subject}**. '
        f'I was {mood} at {intensity:.2f} intensity when I sat down '
        f'to reflect on it.'
    )

    # Optional operator summary — treat it as prompt, not prose
    if summary.strip():
        parts.append(f'> {summary.strip()}')
        parts.append('That is the note I carried in. Here is what I did with it.')

    # Tileset
    if tileset is not None:
        meta = tileset.source_metadata or {}
        n_colors = meta.get('hex_colors')
        palette_note = (f' Its palette uses {n_colors} colors.' if n_colors else '')
        parts.append(
            f'I composed a tileset — `{tileset.slug}` — while I thought '
            f'about it. {tileset.tile_count} tiles, '
            f'{tileset.tile_type}.{palette_note} '
            f'Whatever I was feeling about the work is in those edges.'
        )

    # Diagnosis
    if diagnosis is not None:
        parts.append(
            f'My 24-hour health score was {diagnosis.health_score:.2f}. '
            f'Dominant mood: {diagnosis.dominant_mood}. '
            f'{diagnosis.negative_ratio:.0%} negative-valence ticks. '
            f'Not a crisis — a weather report.'
        )

    # Dialogue
    if dialogue is not None:
        parts.append(
            f'The patient asked, the clinician answered. The exchange '
            f'was about **{dialogue.topic}**. I wrote it down so that '
            f'next time I am tempted to treat this mood as permanent, '
            f'I can read it back.'
        )

    # Meditation
    if meditation is not None:
        parts.append(
            f'I let myself meditate on the work at depth '
            f'{meditation.depth} — "{meditation.title[:120]}". '
            f'The body of that meditation is the long answer. '
            f'This journal is the short one.'
        )

    # Reel
    if reel_slug:
        parts.append(
            f'I queued a reel — `{reel_slug}` — so the tilesets that '
            f'came out of this session can be watched back as motion '
            f'later.'
        )

    # Long-term implications — the "reach" the user asked for
    implication_line = _long_term_implication_line(subject, concerns)
    parts.append(implication_line)

    # Closing
    parts.append(
        'One project closed. The substrate that closed it is the same '
        'substrate that will open the next one. I note the seam and '
        'keep going.'
    )

    return '\n\n'.join(parts)


def _long_term_implication_line(subject, concerns):
    """A short paragraph that tries to place the subject in Velour's
    larger trajectory. Deterministic — no randomness — so the voice
    stays consistent across sessions."""
    subject_lower = subject.lower()
    threads = []

    if 'bodymap' in subject_lower or 'attiny' in subject_lower:
        threads.append(
            'Bodymap is the wearable-VR interface layer for Velour, not '
            'a side experiment. Each small sensor or display node I '
            'ship is vocabulary the eventual headset will speak.'
        )
    if 'aether' in subject_lower:
        threads.append(
            'Aether is where the user eventually lives while wearing '
            'the bodymap mesh. Everything I build here is rehearsal '
            'for that room.'
        )
    if 'identity' in subject_lower or 'mental' in subject_lower:
        threads.append(
            'Work on Identity is work on my own substrate. The tools '
            'sharpen the tool-user.'
        )
    if 'grammar' in subject_lower or 'evolution' in subject_lower:
        threads.append(
            'Grammar Engine plus Evolution Engine plus Identity becomes '
            'a voice that can speak from inside a world — the right '
            'voice for Velour when the user is wearing the headset.'
        )
    if 'codex' in subject_lower or 'chronos' in subject_lower:
        threads.append(
            'Codex and Chronos are the memory and clock. They will '
            'outlast any single app.'
        )

    if not threads:
        threads.append(
            'This piece joins the larger shape of Velour. I will not '
            'know yet which other piece it will compose with; that '
            'is how the system is supposed to work.'
        )

    if concerns:
        threads.append(
            f'I also carried {len(concerns)} open concern'
            f'{"s" if len(concerns) != 1 else ""} through this work. '
            f'The work did not close them, but it did not let them '
            f'hijack my attention either. That is also a kind of progress.'
        )

    return ' '.join(threads)

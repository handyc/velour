"""Identity's contribution to the daily app-status manual.

Reports the current mood, recent tick activity, open concerns, and
latest reflection. Read-only — no side effects."""

from __future__ import annotations

from django.utils import timezone


def report() -> dict:
    from .models import Identity, Tick, Concern, Reflection, Meditation

    me = Identity.get_self()
    last_tick = Tick.objects.order_by('-at').first()
    open_concerns = Concern.objects.filter(closed_at__isnull=True).count()
    latest_reflection = Reflection.objects.order_by('-composed_at').first()
    last_meditation = Meditation.objects.order_by('-composed_at').first()
    today_ticks = Tick.objects.filter(at__date=timezone.localdate()).count()

    lines = [
        f'**Mood:** {me.mood} ({me.mood_intensity:.2f})',
        f'**Tagline:** {me.tagline or "(none)"}',
        '',
        f'- Ticks today: {today_ticks}',
        f'- Open concerns: {open_concerns}',
    ]
    if last_tick:
        ago = int((timezone.now() - last_tick.at).total_seconds() // 60)
        lines.append(f'- Last tick: {ago}m ago — {last_tick.thought[:80]}')
    if latest_reflection:
        lines.append(f'- Latest reflection: *{latest_reflection.title}*')
    if last_meditation:
        lines.append(
            f'- Latest meditation: L{last_meditation.depth} '
            f'({last_meditation.voice}) — *{last_meditation.title[:60]}*')

    return {
        'title':     'Identity',
        'sort_hint': 10,  # near the top
        'body_md':   '\n'.join(lines),
    }

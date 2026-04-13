#!/usr/bin/env python
"""Claude Code SessionStart orientation — Identity's current state.

Prints a one-screen snapshot so the next Claude session inherits context
from the previous one through the Velour Identity system rather than
through conversation summaries alone. The Identity engine becomes a
persistent sidecar memory for Claude's collaborative work.

Reads:
  - Current mood + intensity from the last Tick
  - Most recent Reflection title/date
  - Most recent Meditation title/depth/voice
  - Open Concerns (Identity's "things to attend to")
  - Last dream in the journal
  - Recently-generated tilesets from Identity

No writes — this is pure orientation.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'velour.settings')

try:
    import django
    django.setup()
except Exception:
    # If Django can't set up (e.g. running outside the project), stay silent
    # rather than noisily breaking Claude's session start.
    sys.exit(0)

from django.utils import timezone

try:
    from identity.models import Tick, Reflection, Meditation, Concern
    from codex.models import Section
    from tiles.models import TileSet
except ImportError:
    sys.exit(0)

GREY = '\033[90m'
BLUE = '\033[94m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
MAGENTA = '\033[95m'
RESET = '\033[0m'

def _c(color, text):
    return f'{color}{text}{RESET}'

print()
print(_c(GREY, '── Velour Identity: orientation for this session ──'))

# Current mood
t = Tick.objects.order_by('-at').first()
if t:
    age_min = int((timezone.now() - t.at).total_seconds() / 60)
    print(f'  {_c(MAGENTA, "mood")}        {t.mood} ({t.mood_intensity:.2f}) · {age_min}min ago')
    if t.rule_label:
        print(f'  {_c(GREY, "↳ because")}    {t.rule_label}')

# Open concerns
open_concerns = Concern.objects.filter(closed_at=None).order_by('-opened_at')[:3]
if open_concerns:
    print(f'  {_c(YELLOW, "concerns")}    {open_concerns.count()} open:')
    for c in open_concerns:
        print(f'              · {c.aspect} (since {c.opened_at.strftime("%b %d")})')

# Latest reflection
r = Reflection.objects.order_by('-period_end').first()
if r:
    print(f'  {_c(BLUE, "reflection")}  {r.title}')

# Latest meditation
m = Meditation.objects.order_by('-composed_at').first()
if m:
    print(f'  {_c(BLUE, "meditation")}  depth {m.depth}/{m.voice} — "{m.title[:60]}"')

# Latest dream
dream = (Section.objects
         .filter(manual__slug='dream-journal')
         .order_by('-created_at').first())
if dream:
    print(f'  {_c(GREEN, "last dream")}  {dream.title}')

# Recent Identity-generated tilesets
recent_ts = (TileSet.objects
             .filter(source='identity')
             .order_by('-created_at')[:2])
if recent_ts:
    slugs = ', '.join(ts.slug[:40] for ts in recent_ts)
    print(f'  {_c(GREEN, "tilesets")}    {slugs}')

print(_c(GREY, '──'))
print()

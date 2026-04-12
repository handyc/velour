"""Context processors for the Identity app.

The `topbar_pulse` processor injects Identity's current mood + latest
thought into every template context, so the base template can render
a small ambient indicator next to the chronos clock on every page.
Read-only — it never writes to the database and silently returns an
empty context if anything goes wrong, so a broken Identity never
brings down unrelated pages.
"""


def topbar_pulse(request):
    """Return {'identity_pulse': {...}} for the base template."""
    try:
        from .models import Identity, Tick
        identity = Identity.get_self()
        latest = Tick.objects.first()
        thought = (latest.thought if latest else '') or identity.tagline or ''
        return {
            'identity_pulse': {
                'name':           identity.name,
                'mood':           identity.mood,
                'mood_intensity': identity.mood_intensity,
                'color':          identity.color_preference,
                'thought':        thought,
            },
        }
    except Exception:
        return {}

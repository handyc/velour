"""Template tag library for asset versioning.

Velour's static CSS and JS files are loaded via `{% static_v 'path' %}`
which behaves like Django's `{% static %}` but appends `?v=<mtime>` to
the URL based on the source file's modification time. The browser
treats each new mtime as a fresh URL and bypasses its cache, so a
local edit to chronos.js or style.css is reflected immediately on the
next page load — no manual hard-refresh needed.

In production (where collectstatic has copied files to STATIC_ROOT)
the same mechanism works: every deploy bumps the mtime, every browser
sees a new URL, the cache is invalidated automatically.

If the file can't be located via the staticfiles finders we fall
through to plain `{% static %}` so the include never breaks.

Usage in templates:

    {% load assets %}
    <link rel="stylesheet" href="{% static_v 'css/style.css' %}">
    <script src="{% static_v 'js/chronos.js' %}"></script>
"""

import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static as django_static

register = template.Library()


@register.simple_tag
def static_v(path):
    url = django_static(path)
    abs_path = finders.find(path)
    if abs_path and os.path.isfile(abs_path):
        try:
            mtime = int(os.path.getmtime(abs_path))
        except OSError:
            return url
        sep = '&' if '?' in url else '?'
        return f'{url}{sep}v={mtime}'
    return url

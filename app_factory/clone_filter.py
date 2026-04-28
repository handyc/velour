"""Helpers that rewrite a cloned tree's velour/settings.py and
velour/urls.py to include only the operator-selected apps.

These are pure text transforms — we don't import the cloned settings
(it'd execute it in our process). We rely on the convention that:

- INSTALLED_APPS in settings.py is a single list literal whose entries
  are quoted strings, one per line.
- velour/urls.py's urlpatterns is a single list whose project-app
  entries are ``path('foo/', include('foo.urls'))`` lines, one per line.

That convention holds for the current Velour. If someone reformats
either file, the regexes will need to be revisited.
"""

import re


def _line_matches_app(line, app_slug):
    """Return True if the line names this app as a string literal."""
    return f"'{app_slug}'" in line or f'"{app_slug}"' in line


def filter_installed_apps(settings_text, included_slugs):
    """Rewrite the INSTALLED_APPS block of settings.py to keep only
    the apps in ``included_slugs`` (plus django.* which we never strip).
    Returns the rewritten file text."""
    out_lines = []
    in_block = False
    for line in settings_text.splitlines(keepends=True):
        stripped = line.strip()
        if not in_block:
            out_lines.append(line)
            if stripped.startswith('INSTALLED_APPS'):
                in_block = True
            continue

        # Inside the block — keep django.contrib.* unconditionally,
        # keep included slugs, drop the rest.
        if stripped == ']' or stripped.startswith(']'):
            in_block = False
            out_lines.append(line)
            continue

        if 'django.contrib' in stripped or 'django.' in stripped:
            out_lines.append(line)
            continue

        # Match exactly one quoted slug per line.
        m = re.search(r"['\"]([a-z_][a-z_0-9]*)['\"]", stripped)
        if m:
            slug = m.group(1)
            if slug in included_slugs:
                out_lines.append(line)
            # else: drop the line entirely
            continue

        # Comments, blank lines, anything else inside the block: keep.
        out_lines.append(line)
    return ''.join(out_lines)


def filter_url_includes(urls_text, included_slugs):
    """Rewrite velour/urls.py to drop ``path('foo/', include('foo.urls'))``
    lines whose ``foo`` app is not in ``included_slugs``. Returns the
    rewritten file text."""
    out_lines = []
    # Match: path('something/', include('app_slug.urls'), name='...')
    include_re = re.compile(r"include\(\s*['\"]([a-z_][a-z_0-9]*)\.urls['\"]")
    for line in urls_text.splitlines(keepends=True):
        m = include_re.search(line)
        if not m:
            out_lines.append(line)
            continue
        app_slug = m.group(1)
        if app_slug in included_slugs:
            out_lines.append(line)
        # else: drop
    return ''.join(out_lines)

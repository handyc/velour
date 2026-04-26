"""End-to-end demo: lifted LimeSurvey models served through Django views.

Uses the unmodified `models.py` that `genmodels` produced from the
LimeSurvey MariaDB schema. No source-edits to the lifted code.

The `/typeurl/` view goes one level deeper — it runs an actual
lifted Python class (phpBB's `type_url` profile-field handler,
unmodified from `liftphpcode`) with three stub dependencies so
the methods can execute against live input.
"""
from django.http import HttpResponse
from django.urls import path
from .models import User, Survey, Answer, Question
from .lifted_typeurl import type_url


def index(request):
    """Forum-index analogue — shows counts + first few users."""
    seed_if_empty()
    users = User.objects.all()[:10]
    user_count = User.objects.count()
    survey_count = Survey.objects.count()
    answer_count = Answer.objects.count()

    rows = ''.join(
        f'<tr><td>{u.uid}</td><td>{u.users_name}</td>'
        f'<td>{u.email}</td><td>{u.full_name}</td></tr>'
        for u in users
    )
    return HttpResponse(f"""
<!doctype html><html><head><title>LimeSurvey lifted demo</title>
<style>
body{{font-family:sans-serif;max-width:780px;margin:2em auto;color:#222}}
h1{{font-weight:400;border-bottom:1px solid #888;padding-bottom:0.3em}}
table{{border-collapse:collapse;width:100%;margin-top:1em}}
td,th{{border:1px solid #888;padding:0.4em 0.7em;text-align:left}}
.summary{{background:#eef;padding:0.7em 1em;border-left:3px solid #449}}
</style></head><body>
<h1>LimeSurvey, lifted</h1>
<div class="summary">
This page is served by Django through <code>lime_app.models</code> —
the unmodified <code>models.py</code> that <code>genmodels</code> produced
from the LimeSurvey MariaDB schema. No source-edits to the lifted code.
<br><br>
<strong>{user_count}</strong> users · <strong>{survey_count}</strong> surveys ·
<strong>{answer_count}</strong> answers in the SQLite database right now.
</div>
<h2>First 10 users (lifted ORM round-trip)</h2>
<table>
<thead><tr><th>uid</th><th>users_name</th><th>email</th><th>full_name</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p><em>Refresh to see <code>seed_if_empty()</code> add more rows on
each request — every column was inferred by Datalift from the
SQL CREATE TABLE statement.</em></p>
</body></html>""")


def typeurl_view(request):
    """Run the lifted phpBB `type_url` class against live input."""
    field = type_url()
    test_url = request.GET.get('u', 'https://www.phpbb.com/community/')
    # NOTE: phpBB stores these as strings in the DB so PHP's loose
    # `.` concat works. The lifted Python preserves PHP's
    # string-concat operator (translated to `+`); Python can't
    # concat str + int. Real porters either pass strings (as here)
    # or wrap with `str()` at the call site.
    field_data = {
        'field_required': True,
        'lang_name': 'website_url',
        'field_length': '80',
        'field_minlen': '4',
        'field_maxlen': '200',
    }
    defaults = field.get_default_option_values()
    options_html = field.get_options(1, field_data)
    validation_error = field.validate_profile_field(test_url, field_data)

    # Try a deliberately bad URL too, to show error path works.
    bad_url = 'not-a-url'
    bad_validation = field.validate_profile_field(bad_url, field_data)

    options_table = ''.join(
        f'<tr><td><strong>{opt["TITLE"]}</strong></td>'
        f'<td><code>{opt["FIELD"].replace("<", "&lt;")}</code></td></tr>'
        for opt in options_html.values()
    )
    defaults_rows = ''.join(
        f'<tr><td><code>{k}</code></td><td><code>{v!r}</code></td></tr>'
        for k, v in defaults.items()
    )
    return HttpResponse(f"""
<!doctype html><html><head><title>Lifted phpBB type_url running</title>
<style>
body{{font-family:sans-serif;max-width:780px;margin:2em auto;color:#222}}
h1,h2{{font-weight:400;border-bottom:1px solid #888;padding-bottom:0.3em}}
table{{border-collapse:collapse;width:100%;margin-top:1em}}
td,th{{border:1px solid #888;padding:0.4em 0.7em;text-align:left}}
.summary{{background:#eef;padding:0.7em 1em;border-left:3px solid #449}}
.ok{{color:#160;background:#dfd;padding:0.4em 0.7em;border-left:3px solid #160}}
.fail{{color:#600;background:#fdd;padding:0.4em 0.7em;border-left:3px solid #600}}
code{{background:#f4f4f4;padding:0 0.3em}}
</style></head><body>
<h1>Lifted phpBB <code>type_url</code> — running</h1>
<div class="summary">
This page runs <strong>actual lifted Python</strong>, not just lifted models.
The class <code>type_url</code> is the unmodified <code>liftphpcode</code> output
of <code>phpBB/phpbb/profilefields/type/type_url.php</code> (4 methods).
Three stub dependencies provide just-enough framework context (a
<code>type_string</code> base class, a <code>get_preg_expression</code>
helper, a <code>self.user.lang</code> i18n dict).
</div>

<h2>Method 1: <code>get_default_option_values()</code></h2>
<p>Direct call. Returns a dict of phpBB profile-field defaults.</p>
<table>
<thead><tr><th>key</th><th>value</th></tr></thead>
<tbody>{defaults_rows}</tbody>
</table>

<h2>Method 2: <code>get_options(default_lang_id, field_data)</code></h2>
<p>Builds the HTML form fields. Each row's <code>FIELD</code> is
emitted by the lifted method via PHP-style string concatenation,
translated to Python <code>+</code> by Datalift.</p>
<table>
<thead><tr><th>title</th><th>HTML field</th></tr></thead>
<tbody>{options_table}</tbody>
</table>

<h2>Method 3: <code>validate_profile_field(url, field_data)</code></h2>
<p>Validates a URL against phpBB's <code>url_http</code> regex. Try
<a href="?u=https%3A%2F%2Fexample.com">a good URL</a> or
<a href="?u=not-a-url">a bad one</a>:</p>

<p><strong>Input:</strong> <code>{test_url}</code></p>
<div class="{'fail' if validation_error else 'ok'}">
{'<strong>FAIL:</strong> ' + str(validation_error) if validation_error else
 '<strong>OK</strong> — passes <code>type_url</code> validation'}
</div>

<p><strong>Bad input</strong> (always fails): <code>not-a-url</code></p>
<div class="fail">
<strong>FAIL:</strong> {bad_validation}
</div>

<p><a href="/">← back to schema demo</a></p>
</body></html>""")


def seed_if_empty():
    """Insert sample data if the database is empty."""
    from datetime import datetime
    if User.objects.count() < 3:
        for i, name in enumerate(['alice', 'bob', 'carol', 'dave', 'eve'], 1):
            User.objects.get_or_create(
                users_name=name,
                defaults={
                    'password': '*hashed*',
                    'full_name': name.capitalize() + ' Demo',
                    'email': f'{name}@example.com',
                    'lang': 'en',
                    'parent_id': 0,
                    'created': datetime(2026, 4, 26),
                    'modified': datetime(2026, 4, 26),
                },
            )

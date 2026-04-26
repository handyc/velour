"""End-to-end demo: lifted LimeSurvey models served through Django views.

Uses the unmodified `models.py` that `genmodels` produced from the
LimeSurvey MariaDB schema. No source-edits to the lifted code.
"""
from django.http import HttpResponse
from django.urls import path
from .models import User, Survey, Answer, Question


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

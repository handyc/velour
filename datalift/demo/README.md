# Datalift end-to-end demo — LimeSurvey lifted, served by Django

Captured 2026-04-26 after the AST + shim work brought the
LimeSurvey corpus to ~89% compile rate and the schema layer to
100% functional. This is the smallest *runnable* demonstration of
the toolkit's full chain — schema → models → migrations → ORM
round-trip → Django view → real HTTP response → real screenshot.

## What's here

- `lime_django/` — minimal Django project (~30 lines of glue) that
  hosts the lifted models. Settings just have `SECRET_KEY`,
  SQLite, and `lime_app` in `INSTALLED_APPS`.
- `lime_django/lime_app/models.py` — **the unmodified `models.py`
  that `genmodels` produced from the LimeSurvey MariaDB schema**.
  No source-edits. 45 model classes, 1,400 lines.
- `lime_django/lime_app/views.py` — one Django view (`index`)
  that uses the lifted models for a real ORM round-trip and
  renders the result as HTML.
- `lime_django_demo.html` — the actual HTTP response body
  captured from `manage.py runserver`.
- `lime_django_demo.png` — full-page screenshot via Velour's
  `browsershot` command, rendered through real Chromium.

## How to reproduce

```bash
cd datalift/demo/lime_django
PYTHONPATH=../../.. /path/to/venv/bin/python manage.py migrate
PYTHONPATH=../../.. /path/to/venv/bin/python manage.py runserver 7778
# browse http://127.0.0.1:7778/
```

## What it proves

End-to-end:

1. `genmodels` → `models.py` was accepted by Django's
   `manage.py check` with **0 issues** (45 models, every field
   inferred from the SQL CREATE TABLE statement).
2. `manage.py makemigrations` generated a clean initial migration
   covering all 45 `lime_*` tables.
3. `manage.py migrate` applied them — every table created in
   SQLite, composite primary keys + uniqueness constraints honored.
4. The Django view inserts `User` rows via the lifted ORM
   (`User.objects.create(...)`), reads them back via
   `User.objects.all()`, and renders an HTML table from the
   results. Defaults defined in the lifted model
   (`language='en'`, `scale_id=0`) are auto-applied.
5. `manage.py runserver` boots the app on port 7778 and returns
   HTTP 200, 1,562 bytes of HTML, in 8ms.
6. Velour's `browsershot` command (real Chromium) renders the
   page exactly as the screenshot shows.

This is the layer of "is the toolkit actually useful?" beyond
"does the lifted code compile?" — and the answer is **yes**, for
the schema layer, with **zero porter intervention**.

The corresponding statement for the *application code* layer is
weaker: 89.4% of LimeSurvey's `application/` PHP files compile
to valid Python via `liftphpcode`, but they need framework
dependencies (Yii's request / response / session / template
machinery) wired in for real use. That layer is in scope for a
larger porter project, not a one-session demo.

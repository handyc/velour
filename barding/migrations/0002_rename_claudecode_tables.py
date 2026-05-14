"""Rename leftover claudecode_* tables to barding_*.

Background: the app was originally registered as ``claudecode`` and
its initial migration (0001_initial) created tables named
``claudecode_settingsscope`` and ``claudecode_bundlepatchwish``.
On 2026-05-14 the app was renamed to ``barding`` for clarity
(commit 9e82f70).  Django now constructs table names from the new
``barding`` label by default, so existing databases — which still
hold the data in the old ``claudecode_*`` tables — start raising
``OperationalError: no such table: barding_settingsscope`` the
moment a barding view tries to query.

This migration runs a stateless SQL rename on each affected table
when the old name still exists, and is a no-op on fresh databases
(those will have created ``barding_*`` tables outright from
0001_initial after the rename).
"""

from django.db import migrations


SQL_FORWARD = """
-- SQLite + Postgres both accept ALTER TABLE ... RENAME TO.
-- We don't gate on existence at the migration level; the IF EXISTS
-- equivalent is to issue the rename inside a try/except in a
-- RunPython, but here we use a simple conditional approach via
-- Django's connection introspection (see the RunPython below).
"""


def forwards(apps, schema_editor):
    """Rename the two known old tables to their new names — only when
    the old name exists.  Fresh installs (where 0001_initial built
    barding_* directly) are no-ops."""
    connection = schema_editor.connection
    existing = set(connection.introspection.table_names())
    pairs = [
        ('claudecode_settingsscope',   'barding_settingsscope'),
        ('claudecode_bundlepatchwish', 'barding_bundlepatchwish'),
    ]
    with connection.cursor() as cur:
        for old, new in pairs:
            if old in existing and new not in existing:
                cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')


def backwards(apps, schema_editor):
    connection = schema_editor.connection
    existing = set(connection.introspection.table_names())
    pairs = [
        ('barding_settingsscope',   'claudecode_settingsscope'),
        ('barding_bundlepatchwish', 'claudecode_bundlepatchwish'),
    ]
    with connection.cursor() as cur:
        for old, new in pairs:
            if old in existing and new not in existing:
                cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')


class Migration(migrations.Migration):

    dependencies = [
        ('barding', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

"""Rescue data from the orphaned claudecode_* tables.

Concrete sequence of events that produced the bug this migration
fixes:

1. App was originally registered as ``claudecode`` and migration
   0001_initial created ``claudecode_settingsscope`` /
   ``claudecode_bundlepatchwish``.  Data accumulated in those.
2. App was renamed to ``barding`` (commit 9e82f70).  Models are
   identical but Django now derives table names from the new label.
3. Running ``manage.py migrate`` after the rename:
   - sees the ``barding`` app has 0001_initial unapplied (different
     app label = different migration-history row);
   - applies it fresh, creating empty ``barding_*`` tables.
   The old ``claudecode_*`` tables are untouched but now invisible
   to the ORM, and the live ``barding_*`` tables are empty.
4. Migration 0002_rename_claudecode_tables checks
   ``new not in existing`` before renaming, so once the empty
   barding_* tables exist it correctly bails — but that leaves the
   data orphaned.

This migration does the right thing for that combined state:
when ``claudecode_X`` has rows and ``barding_X`` is empty, drop
the empty barding_X and ``ALTER TABLE claudecode_X RENAME TO
barding_X``.  Then clear the orphaned ``claudecode.0001_initial``
row from ``django_migrations`` so future ``manage.py migrate``
runs don't try to re-create empty tables under either label.
"""

from django.db import migrations


def _table_row_count(connection, name: str) -> int | None:
    """Return row count for ``name``, or ``None`` if the table is
    missing."""
    existing = set(connection.introspection.table_names())
    if name not in existing:
        return None
    with connection.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{name}"')
        return cur.fetchone()[0]


def forwards(apps, schema_editor):
    connection = schema_editor.connection
    pairs = [
        ('claudecode_settingsscope',   'barding_settingsscope'),
        ('claudecode_bundlepatchwish', 'barding_bundlepatchwish'),
    ]
    with connection.cursor() as cur:
        for old, new in pairs:
            old_count = _table_row_count(connection, old)
            new_count = _table_row_count(connection, new)
            if old_count is None:
                continue                # nothing to rescue
            # The interesting case: old has data, new exists but is empty.
            if new_count == 0:
                cur.execute(f'DROP TABLE "{new}"')
                cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
            elif new_count is None:
                cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
            else:
                # Both populated: leave the user to resolve.  We don't
                # silently lose rows.
                continue
        # Drop the orphaned 'claudecode' app row from django_migrations
        # so future migrate runs don't reapply 0001 under the dead
        # label and recreate empty tables again.
        cur.execute("DELETE FROM django_migrations WHERE app = 'claudecode'")


def backwards(apps, schema_editor):
    connection = schema_editor.connection
    pairs = [
        ('barding_settingsscope',   'claudecode_settingsscope'),
        ('barding_bundlepatchwish', 'claudecode_bundlepatchwish'),
    ]
    with connection.cursor() as cur:
        for old, new in pairs:
            existing = set(connection.introspection.table_names())
            if old in existing and new not in existing:
                cur.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')


class Migration(migrations.Migration):

    dependencies = [
        ('barding', '0002_rename_claudecode_tables'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

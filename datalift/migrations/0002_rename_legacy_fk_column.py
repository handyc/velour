"""Idempotent column rename: `source_db_ref_id` → `source_db_ref`.

The original 0001_initial declared source_db_ref as a ForeignKey to
databases.Database, which caused Django to use the `_id` suffix at
the DB layer. 0001_initial has since been rewritten to declare it as
a plain PositiveIntegerField (no `_id` suffix, no cross-app
dependency), so velour's already-applied DB column needs a one-off
rename to catch up. Fresh installs don't need this migration — the
check below short-circuits.
"""

from django.db import migrations


def rename_old_fk_column(apps, schema_editor):
    conn = schema_editor.connection
    cols = _column_names(conn, 'datalift_liftjob')
    if 'source_db_ref_id' in cols and 'source_db_ref' not in cols:
        with conn.cursor() as cur:
            if conn.vendor in ('sqlite', 'postgresql'):
                cur.execute(
                    'ALTER TABLE datalift_liftjob '
                    'RENAME COLUMN source_db_ref_id TO source_db_ref'
                )
            elif conn.vendor == 'mysql':
                # MySQL's RENAME COLUMN needs 8.0+; CHANGE works on
                # all versions but requires restating the type.
                cur.execute(
                    'ALTER TABLE datalift_liftjob '
                    'CHANGE source_db_ref_id source_db_ref INT UNSIGNED NULL'
                )


def _column_names(conn, table):
    with conn.cursor() as cur:
        if conn.vendor == 'sqlite':
            cur.execute(f'PRAGMA table_info({table})')
            return {row[1] for row in cur.fetchall()}
        if conn.vendor in ('postgresql', 'mysql'):
            cur.execute(
                'SELECT column_name FROM information_schema.columns '
                'WHERE table_name = %s', [table])
            return {row[0] for row in cur.fetchall()}
    return set()


class Migration(migrations.Migration):

    dependencies = [
        ('datalift', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(rename_old_fk_column, migrations.RunPython.noop),
    ]

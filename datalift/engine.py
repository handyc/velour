"""Datalift engine: MySQL/MariaDB introspection, Django model generation,
SQLite population, and data anonymization."""

import os
import random
import re
import sqlite3
import string
import tempfile
from collections import OrderedDict

import pymysql


def _quoted_cols(col_names):
    return ', '.join(f'"{c}"' for c in col_names)


# ---------------------------------------------------------------------------
# MySQL introspection
# ---------------------------------------------------------------------------

def connect_mysql(host, port, user, password, database):
    return pymysql.connect(
        host=host, port=int(port), user=user, password=password,
        database=database, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )


def introspect_tables(conn):
    """Return {table_name: [column_info_dict, ...]} for all tables."""
    tables = OrderedDict()
    with conn.cursor() as cur:
        cur.execute('SHOW TABLES')
        table_names = [list(row.values())[0] for row in cur.fetchall()]

    for tname in sorted(table_names):
        with conn.cursor() as cur:
            cur.execute(f'DESCRIBE `{tname}`')
            columns = cur.fetchall()
        tables[tname] = columns
    return tables


def get_row_count(conn, table):
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) AS cnt FROM `{table}`')
        return cur.fetchone()['cnt']


def fetch_rows(conn, table, limit=50000):
    with conn.cursor() as cur:
        cur.execute(f'SELECT * FROM `{table}` LIMIT {limit}')
        return cur.fetchall()


# ---------------------------------------------------------------------------
# MySQL type → Django field mapping
# ---------------------------------------------------------------------------

def mysql_type_to_django(col):
    """Map a MySQL column description to a Django field string."""
    raw = col['Type'].lower()
    field = col['Field']
    null = col['Null'] == 'YES'
    default = col['Default']
    key = col['Key']
    extra = col.get('Extra', '')

    null_str = ', null=True, blank=True' if null else ''
    default_str = ''
    if default is not None and default != '' and 'auto_increment' not in extra:
        if isinstance(default, str):
            default_str = f", default='{default}'"
        else:
            default_str = f', default={default}'

    # Auto-increment primary key
    if 'auto_increment' in extra:
        return 'models.AutoField(primary_key=True)'

    # Integer types
    if raw.startswith('tinyint(1)') or raw == 'boolean' or raw == 'bool':
        return f'models.BooleanField(default=False{null_str})'
    if 'bigint' in raw:
        return f'models.BigIntegerField({null_str}{default_str})'
    if 'smallint' in raw:
        return f'models.SmallIntegerField({null_str}{default_str})'
    if 'mediumint' in raw or 'int' in raw:
        if 'unsigned' in raw:
            return f'models.PositiveIntegerField({null_str}{default_str})'
        return f'models.IntegerField({null_str}{default_str})'

    # Float / double / decimal
    m = re.match(r'decimal\((\d+),(\d+)\)', raw)
    if m:
        return f'models.DecimalField(max_digits={m.group(1)}, decimal_places={m.group(2)}{null_str}{default_str})'
    if 'double' in raw or 'float' in raw:
        return f'models.FloatField({null_str}{default_str})'

    # String types
    m = re.match(r'varchar\((\d+)\)', raw)
    if m:
        return f'models.CharField(max_length={m.group(1)}{null_str}{default_str})'
    if 'char(' in raw:
        m2 = re.match(r'char\((\d+)\)', raw)
        ml = m2.group(1) if m2 else '255'
        return f'models.CharField(max_length={ml}{null_str}{default_str})'

    # Text types
    if 'longtext' in raw or 'mediumtext' in raw or raw == 'text' or 'tinytext' in raw:
        return f'models.TextField({null_str})'

    # Binary / blob
    if 'blob' in raw or 'binary' in raw:
        return f'models.BinaryField({null_str})'

    # Date / time
    if raw == 'date':
        return f'models.DateField({null_str}{default_str})'
    if raw == 'time':
        return f'models.TimeField({null_str}{default_str})'
    if 'datetime' in raw or 'timestamp' in raw:
        return f'models.DateTimeField({null_str}{default_str})'
    if raw == 'year':
        return f'models.PositiveSmallIntegerField({null_str}{default_str})'

    # Enum
    m = re.match(r"enum\((.+)\)", raw)
    if m:
        vals = re.findall(r"'([^']*)'", m.group(1))
        max_len = max(len(v) for v in vals) if vals else 50
        choices = ', '.join(f"('{v}', '{v}')" for v in vals)
        return f'models.CharField(max_length={max_len}, choices=[{choices}]{null_str}{default_str})'

    # JSON
    if raw == 'json':
        return f'models.JSONField(default=dict{null_str})'

    # Fallback
    return f'models.TextField({null_str})  # unmapped: {raw}'


# ---------------------------------------------------------------------------
# Generate Django models.py
# ---------------------------------------------------------------------------

def table_to_model_name(table_name):
    """Convert table_name to PascalCase model name."""
    parts = re.split(r'[_\-\s]+', table_name)
    return ''.join(p.capitalize() for p in parts)


def field_name_clean(field):
    """Make a MySQL column name safe for Django."""
    name = field.lower().strip()
    name = re.sub(r'[^a-z0-9_]', '_', name)
    if name[0].isdigit():
        name = 'f_' + name
    # Avoid Python keywords
    if name in ('class', 'import', 'pass', 'return', 'def', 'global', 'for',
                'while', 'if', 'else', 'elif', 'try', 'except', 'with', 'as',
                'from', 'in', 'is', 'not', 'and', 'or', 'lambda', 'yield'):
        name = name + '_field'
    return name


def generate_models_py(tables, app_label='converted'):
    """Generate a complete models.py from the introspected tables."""
    lines = [
        '# Auto-generated by Datalift',
        '# Source: MySQL / MariaDB introspection',
        '',
        'from django.db import models',
        '',
    ]

    for table_name, columns in tables.items():
        model_name = table_to_model_name(table_name)
        lines.append(f'')
        lines.append(f'class {model_name}(models.Model):')
        lines.append(f'    """Generated from table `{table_name}`."""')

        has_pk = any('auto_increment' in (c.get('Extra', '')) for c in columns)

        for col in columns:
            fname = field_name_clean(col['Field'])
            fdef = mysql_type_to_django(col)

            # Strip leading comma+space from first kwarg if field starts with it
            fdef = re.sub(r'\(\s*,\s*', '(', fdef)

            lines.append(f'    {fname} = {fdef}')

        lines.append('')
        lines.append(f'    class Meta:')
        lines.append(f"        db_table = '{table_name}'")
        if not has_pk:
            lines.append(f'        managed = True')
        lines.append('')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Populate SQLite from MySQL data
# ---------------------------------------------------------------------------

def mysql_to_sqlite_type(col):
    raw = col['Type'].lower()
    if 'int' in raw:
        return 'INTEGER'
    if 'float' in raw or 'double' in raw or 'decimal' in raw:
        return 'REAL'
    if 'blob' in raw or 'binary' in raw:
        return 'BLOB'
    return 'TEXT'


def convert_to_sqlite(conn, tables, output_path):
    """Create a SQLite database with the same schema and data."""
    sconn = sqlite3.connect(output_path)
    total_rows = 0

    for table_name, columns in tables.items():
        # Create table
        col_defs = []
        for col in columns:
            fname = col['Field']
            stype = mysql_to_sqlite_type(col)
            pk = ' PRIMARY KEY' if 'auto_increment' in col.get('Extra', '') else ''
            nn = ' NOT NULL' if col['Null'] != 'YES' and not pk else ''
            col_defs.append(f'"{fname}" {stype}{pk}{nn}')

        create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
        sconn.execute(create_sql)

        # Copy data
        rows = fetch_rows(conn, table_name)
        if rows:
            col_names = [col['Field'] for col in columns]
            placeholders = ', '.join(['?'] * len(col_names))
            insert_sql = f'INSERT INTO "{table_name}" ({_quoted_cols(col_names)}) VALUES ({placeholders})'
            for row in rows:
                vals = []
                for cn in col_names:
                    v = row.get(cn)
                    if isinstance(v, bytes):
                        vals.append(v)
                    elif v is None:
                        vals.append(None)
                    else:
                        vals.append(str(v))
                sconn.execute(insert_sql, vals)
            total_rows += len(rows)

        sconn.commit()

    sconn.close()
    return total_rows


# ---------------------------------------------------------------------------
# Anonymization engine
# ---------------------------------------------------------------------------

def anonymize_char(ch):
    """Replace a character with a random character of the same class."""
    if ch.isupper():
        return random.choice(string.ascii_uppercase)
    if ch.islower():
        return random.choice(string.ascii_lowercase)
    if ch.isdigit():
        return random.choice(string.digits)
    # Preserve whitespace, punctuation, special chars
    return ch


def anonymize_value(val):
    """Anonymize a single value, preserving type and structure."""
    if val is None:
        return None
    if isinstance(val, bytes):
        return bytes(random.randint(0, 255) for _ in val)
    if isinstance(val, bool):
        return random.choice([True, False])
    if isinstance(val, int):
        if val == 0:
            return 0
        sign = 1 if val >= 0 else -1
        magnitude = len(str(abs(val)))
        low = 10 ** (magnitude - 1) if magnitude > 1 else 0
        high = 10 ** magnitude - 1
        return sign * random.randint(low, high)
    if isinstance(val, float):
        if val == 0.0:
            return 0.0
        s = str(val)
        return float(''.join(anonymize_char(c) for c in s))
    if isinstance(val, str):
        # Preserve structure: same length, same char classes
        return ''.join(anonymize_char(c) for c in val)
    # For date/datetime objects, shift by random days
    import datetime
    if isinstance(val, datetime.datetime):
        delta = datetime.timedelta(days=random.randint(-365, 365),
                                   seconds=random.randint(0, 86399))
        return val + delta
    if isinstance(val, datetime.date):
        delta = datetime.timedelta(days=random.randint(-365, 365))
        return val + delta
    if isinstance(val, datetime.time):
        return datetime.time(random.randint(0, 23), random.randint(0, 59),
                             random.randint(0, 59))
    return val


def anonymize_to_sqlite(conn, tables, output_path):
    """Create an anonymized SQLite copy of the MySQL database."""
    sconn = sqlite3.connect(output_path)
    total_rows = 0

    for table_name, columns in tables.items():
        # Create table (same schema)
        col_defs = []
        for col in columns:
            fname = col['Field']
            stype = mysql_to_sqlite_type(col)
            pk = ' PRIMARY KEY' if 'auto_increment' in col.get('Extra', '') else ''
            nn = ' NOT NULL' if col['Null'] != 'YES' and not pk else ''
            col_defs.append(f'"{fname}" {stype}{pk}{nn}')

        create_sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" ({", ".join(col_defs)})'
        sconn.execute(create_sql)

        # Copy + anonymize data
        rows = fetch_rows(conn, table_name)
        if rows:
            col_names = [col['Field'] for col in columns]
            placeholders = ', '.join(['?'] * len(col_names))
            insert_sql = f'INSERT INTO "{table_name}" ({_quoted_cols(col_names)}) VALUES ({placeholders})'

            # Detect which columns are likely PKs or FKs (preserve referential integrity)
            pk_cols = {col['Field'] for col in columns
                       if col['Key'] == 'PRI' or 'auto_increment' in col.get('Extra', '')}

            for row in rows:
                vals = []
                for cn in col_names:
                    v = row.get(cn)
                    if cn in pk_cols:
                        # Preserve primary keys for referential integrity
                        vals.append(v if v is None else str(v))
                    else:
                        anon = anonymize_value(v)
                        if isinstance(anon, bytes):
                            vals.append(anon)
                        elif anon is None:
                            vals.append(None)
                        else:
                            vals.append(str(anon))
                sconn.execute(insert_sql, vals)
            total_rows += len(rows)

        sconn.commit()

    sconn.close()
    return total_rows


# ---------------------------------------------------------------------------
# Anonymize a SQLite file directly (for any-format support)
# ---------------------------------------------------------------------------

def anonymize_sqlite_file(input_path, output_path):
    """Read a SQLite file, anonymize all non-PK data, write to output."""
    import shutil
    shutil.copy2(input_path, output_path)

    sconn = sqlite3.connect(output_path)
    sconn.row_factory = sqlite3.Row

    cur = sconn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    table_names = [r['name'] for r in cur.fetchall()
                   if not r['name'].startswith('sqlite_')]

    total_rows = 0
    for tname in table_names:
        # Get column info
        cur = sconn.execute(f'PRAGMA table_info("{tname}")')
        cols = cur.fetchall()
        pk_cols = {c['name'] for c in cols if c['pk'] > 0}
        all_cols = [c['name'] for c in cols]
        non_pk = [c for c in all_cols if c not in pk_cols]

        if not non_pk:
            continue

        cur = sconn.execute(f'SELECT * FROM "{tname}"')
        rows = cur.fetchall()

        # Delete and re-insert with anonymized data
        sconn.execute(f'DELETE FROM "{tname}"')

        placeholders = ', '.join(['?'] * len(all_cols))
        insert_sql = f'INSERT INTO "{tname}" ({_quoted_cols(all_cols)}) VALUES ({placeholders})'

        for row in rows:
            vals = []
            for cn in all_cols:
                v = row[cn]
                if cn in pk_cols:
                    vals.append(v)
                else:
                    vals.append(anonymize_value(v))
            sconn.execute(insert_sql, vals)
            total_rows += 1

        sconn.commit()

    sconn.close()
    return total_rows

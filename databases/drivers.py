"""Driver glue for the Databases app.

test_connection(db) — trivial SELECT 1 / version query, returns version
string or raises.

SQLite functions for table browsing:
  list_tables(db)       → [{name, row_count, col_count}, ...]
  table_columns(db, t)  → [{name, type, notnull, pk, dflt_value}, ...]
  table_rows(db, t, limit, offset) → (column_names, rows_list)
  run_query(db, sql)    → (column_names, rows_list)  (read-only)
  create_sqlite_file(path) → creates an empty SQLite database

Drivers are imported lazily so the app remains usable even if a
particular driver hasn't been installed yet.
"""

import os
import sqlite3


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

def _test_sqlite(db):
    if not db.file_path:
        raise RuntimeError('No file path set for this SQLite database.')
    if not os.path.isfile(db.file_path):
        raise RuntimeError(f'File not found: {db.file_path}')
    conn = sqlite3.connect(db.file_path)
    try:
        cur = conn.execute('SELECT sqlite_version()')
        version = cur.fetchone()[0]
    finally:
        conn.close()
    return f'SQLite {version}'


def _test_mysql(db):
    try:
        import pymysql
    except ImportError as e:
        raise RuntimeError(
            'pymysql is not installed. Run: pip install pymysql'
        ) from e

    kwargs = dict(
        host=db.host,
        port=db.effective_port,
        user=db.username or '',
        password=db.password or '',
        connect_timeout=5,
        read_timeout=5,
        write_timeout=5,
    )
    if db.database_name:
        kwargs['database'] = db.database_name
    if db.ssl_mode and db.ssl_mode != 'disable':
        kwargs['ssl'] = {}  # tells pymysql to enable TLS with system trust

    conn = pymysql.connect(**kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT VERSION()')
            row = cur.fetchone()
            version = row[0] if row else 'unknown'
    finally:
        conn.close()
    return f'MySQL {version}'


def _test_postgresql(db):
    try:
        import psycopg
    except ImportError as e:
        raise RuntimeError(
            'psycopg is not installed. Run: pip install "psycopg[binary]"'
        ) from e

    parts = [
        f'host={db.host}',
        f'port={db.effective_port}',
        f'user={db.username or ""}',
        f'password={db.password or ""}',
        'connect_timeout=5',
    ]
    if db.database_name:
        parts.append(f'dbname={db.database_name}')
    if db.ssl_mode:
        parts.append(f'sslmode={db.ssl_mode}')

    conn = psycopg.connect(' '.join(parts))
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT version()')
            row = cur.fetchone()
            version = row[0] if row else 'unknown'
    finally:
        conn.close()
    return version[:120]


_DISPATCH = {
    'sqlite':     _test_sqlite,
    'mysql':      _test_mysql,
    'postgresql': _test_postgresql,
}


def test_connection(db):
    """Run a trivial query against `db`. Returns server version on success,
    raises RuntimeError or driver-specific exception on failure."""
    fn = _DISPATCH.get(db.engine)
    if fn is None:
        raise RuntimeError(f'Unknown engine: {db.engine}')
    return fn(db)


# ---------------------------------------------------------------------------
# SQLite browsing
# ---------------------------------------------------------------------------

def _sqlite_conn(db):
    if not db.file_path or not os.path.isfile(db.file_path):
        raise RuntimeError(f'SQLite file not found: {db.file_path}')
    conn = sqlite3.connect(db.file_path)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(db):
    """Return list of dicts: {name, row_count, col_count}."""
    conn = _sqlite_conn(db)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = []
        for row in cur.fetchall():
            tname = row['name']
            rc = conn.execute(f'SELECT COUNT(*) FROM "{tname}"').fetchone()[0]
            ci = conn.execute(f'PRAGMA table_info("{tname}")').fetchall()
            tables.append({'name': tname, 'row_count': rc, 'col_count': len(ci)})
        return tables
    finally:
        conn.close()


def table_columns(db, table_name):
    """Return column info for a table: [{name, type, notnull, pk, dflt_value}]."""
    conn = _sqlite_conn(db)
    try:
        cur = conn.execute(f'PRAGMA table_info("{table_name}")')
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def table_rows(db, table_name, limit=200, offset=0):
    """Return (column_names, rows) for a table."""
    conn = _sqlite_conn(db)
    try:
        cols = [c['name'] for c in
                conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
        cur = conn.execute(
            f'SELECT * FROM "{table_name}" LIMIT ? OFFSET ?',
            (limit, offset),
        )
        rows = [list(row) for row in cur.fetchall()]
        return cols, rows
    finally:
        conn.close()


def run_query(db, sql):
    """Execute a read-only SQL statement, return (column_names, rows).
    Writes are blocked by opening in read-only mode."""
    if not db.file_path or not os.path.isfile(db.file_path):
        raise RuntimeError(f'SQLite file not found: {db.file_path}')
    uri = f'file:{db.file_path}?mode=ro'
    conn = sqlite3.connect(uri, uri=True)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return cols, rows
    finally:
        conn.close()


def create_sqlite_file(path):
    """Create an empty SQLite database at the given path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.close()

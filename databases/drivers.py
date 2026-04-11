"""Driver glue for the Databases app.

Each backend exposes a single function: `test(db)` which connects,
runs a trivial query, fetches the server version string, and either
returns the version or raises an exception with a useful message.

Drivers are imported lazily so the app remains usable even if a
particular driver hasn't been installed yet — the test will simply
report "driver not installed" for that engine.
"""


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
    # The full version string is verbose ("PostgreSQL 16.1 on x86_64-…")
    # — first ~80 chars is enough for the UI.
    return version[:120]


_DISPATCH = {
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

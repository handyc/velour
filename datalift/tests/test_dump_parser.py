"""Regression tests for datalift.dump_parser.

Each test is a minimal inline SQL fixture that reproduces a specific
bug we've previously landed a fix for. The bug's source corpus is
named in the test docstring so future debuggers have a thread to
pull on.

Run via:
    venv/bin/python manage.py test datalift.tests.test_dump_parser
"""

from django.test import SimpleTestCase

from datalift.dump_parser import (
    _parse_value,
    _strip_table_prefix_placeholders,
    iter_create_tables,
    iter_inserts,
)


class TablePrefixPlaceholderTests(SimpleTestCase):
    """Each legacy framework invents a new table-prefix placeholder
    syntax. The helper strips the lot so downstream sees clean
    identifier names."""

    def test_mediawiki_comment_prefix(self):
        # MediaWiki: `CREATE TABLE /*_*/actor`
        self.assertEqual(_strip_table_prefix_placeholders('/*_*/actor'), 'actor')

    def test_wordpress_php_variable(self):
        # WordPress: `$wpdb->posts`
        self.assertEqual(_strip_table_prefix_placeholders('$wpdb->posts'), 'posts')

    def test_wordpress_braced_php_variable(self):
        self.assertEqual(
            _strip_table_prefix_placeholders('${wpdb}->termmeta'),
            'termmeta',
        )

    def test_joomla_hash_prefix(self):
        # Joomla installer: `#__users`
        self.assertEqual(_strip_table_prefix_placeholders('#__users'), 'users')

    def test_prestashop_literal_prefix(self):
        # PrestaShop / osCommerce: `PREFIX_orders`
        self.assertEqual(
            _strip_table_prefix_placeholders('PREFIX_orders'),
            'orders',
        )
        self.assertEqual(
            _strip_table_prefix_placeholders('DB_PREFIX_customers'),
            'customers',
        )

    def test_generic_curly_brace(self):
        self.assertEqual(
            _strip_table_prefix_placeholders('{TABLE_PREFIX}_nodes'),
            'nodes',
        )

    def test_postgres_schema_qualifier(self):
        # pg_dump: `public.customer`
        self.assertEqual(
            _strip_table_prefix_placeholders('public.customer'),
            'customer',
        )
        # SQL Server default `dbo` schema
        self.assertEqual(
            _strip_table_prefix_placeholders('dbo.Orders'),
            'Orders',
        )

    def test_postgres_quoted_per_segment(self):
        # pg_dump sometimes: `"public"."my_table"`
        self.assertEqual(
            _strip_table_prefix_placeholders('"public"."my_table"'),
            'my_table',
        )


class IterCreateTablesTests(SimpleTestCase):
    """`iter_create_tables` must yield exactly the declared CREATE
    TABLE statements, without consuming neighbours. The historical
    failure mode was the paren walker flipping into fake
    string-state on an apostrophe inside a line comment."""

    def test_two_tables_parse(self):
        sql = """
            CREATE TABLE a (id INT);
            CREATE TABLE b (id INT);
        """
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['a', 'b'])

    def test_apostrophe_in_line_comment_does_not_eat_next_table(self):
        # Dolibarr regression: a French-language `-- d'un element`
        # comment was swallowing subsequent tables because the paren
        # walker saw the `'` and flipped into inside-a-string mode.
        sql = """
            CREATE TABLE first_table (
                id INT
                -- d'un element sert de reference
            );
            CREATE TABLE second_table (
                id INT
            );
        """
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['first_table', 'second_table'])

    def test_apostrophe_in_block_comment_does_not_eat_next_table(self):
        sql = """
            CREATE TABLE a (
                id INT
                /* something's here and something */
            );
            CREATE TABLE b (id INT);
        """
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['a', 'b'])

    def test_hash_comment_is_skipped(self):
        # MySQL's # line comment.
        sql = """
            CREATE TABLE a (
                id INT  # here's a comment with apostrophe
            );
            CREATE TABLE b (id INT);
        """
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['a', 'b'])

    def test_table_name_without_space_before_paren(self):
        # Dolibarr / MyBB style: `create table tbl(...)` — no space
        # between the name and the opening paren. The literal
        # `llx_` prefix is stripped later by
        # `table_to_model_name`'s common-prefix detection, not here.
        sql = "create table llx_users(id int);"
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['llx_users'])

    def test_lowercase_create_table(self):
        sql = "create table foo (id int);"
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['foo'])

    def test_schema_qualified_name_from_pg_dump(self):
        sql = """
            CREATE TABLE public.customer (
                customer_id integer NOT NULL
            );
        """
        names = [n for n, _ in iter_create_tables(sql)]
        self.assertEqual(names, ['customer'])


class IterInsertsTests(SimpleTestCase):
    """`iter_inserts` must ignore INSERTs that live inside SQL line
    comments (Joomla, Dolibarr both ship with bash snippets that
    literally contain `INSERT INTO ...` inside `-- …` comments)."""

    def test_simple_insert(self):
        sql = "INSERT INTO actor VALUES (1, 'PENELOPE', 'GUINESS');"
        rows = list(iter_inserts(sql))
        self.assertEqual(len(rows), 1)
        table, cols, data = rows[0]
        self.assertEqual(table, 'actor')
        self.assertEqual(cols, None)
        self.assertEqual(data, [(1, 'PENELOPE', 'GUINESS')])

    def test_insert_with_explicit_column_list_no_space(self):
        # Dolibarr: `INSERT INTO tbl(col1, col2) VALUES …`
        sql = "INSERT INTO tbl(code, name) VALUES ('FR', 'France');"
        rows = list(iter_inserts(sql))
        self.assertEqual(len(rows), 1)
        table, cols, data = rows[0]
        self.assertEqual(table, 'tbl')
        self.assertEqual(cols, ['code', 'name'])
        self.assertEqual(data, [('FR', 'France')])

    def test_line_comment_with_fake_insert_is_ignored(self):
        # Dolibarr: bash scripts in `--` comments contain literal
        # `INSERT INTO ...` strings that our regex would otherwise
        # match as real data.
        sql = """
            -- for x in {1..100}; do echo "INSERT INTO fake VALUES ($x);"; done
            INSERT INTO real_table VALUES (1);
        """
        tables = [t for t, _, _ in iter_inserts(sql)]
        self.assertEqual(tables, ['real_table'])

    def test_schema_qualified_insert(self):
        # pg_dump: `INSERT INTO public.actor VALUES …`
        sql = "INSERT INTO public.actor VALUES (1, 'P');"
        tables = [t for t, _, _ in iter_inserts(sql)]
        self.assertEqual(tables, ['actor'])


class ParseValueTests(SimpleTestCase):
    """`_parse_value` handles the full menagerie of value shapes we've
    encountered in real dumps."""

    def _parse(self, text):
        val, _ = _parse_value(text, 0)
        return val

    def test_integer(self):
        self.assertEqual(self._parse('42'), 42)

    def test_negative_integer(self):
        self.assertEqual(self._parse('-7'), -7)

    def test_float(self):
        self.assertEqual(self._parse('3.14'), 3.14)

    def test_quoted_string(self):
        self.assertEqual(self._parse("'PENELOPE'"), 'PENELOPE')

    def test_null_keyword(self):
        self.assertIsNone(self._parse('NULL'))

    def test_hex_literal(self):
        # mysqldump BLOB: 0xDEADBEEF
        self.assertEqual(self._parse('0xDEADBEEF'), b'\xde\xad\xbe\xef')

    def test_sqlserver_unicode_prefix(self):
        # Chinook: `N'Rock'` — SQL Server Unicode literal prefix.
        self.assertEqual(self._parse("N'Rock'"), 'Rock')

    def test_bareword_true_is_python_true(self):
        # Pagila / Postgres: `VALUES (…, true, …)`
        self.assertIs(self._parse('true'), True)
        self.assertIs(self._parse('TRUE'), True)

    def test_bareword_false_is_python_false(self):
        self.assertIs(self._parse('false'), False)
        self.assertIs(self._parse('FALSE'), False)

    def test_current_timestamp_function_returns_datetime(self):
        # Joomla: `CURRENT_TIMESTAMP()` inside VALUES. Earlier this
        # crashed the tuple parser (paren it couldn't handle).
        from datetime import datetime
        val = self._parse('CURRENT_TIMESTAMP()')
        self.assertIsInstance(val, datetime)

    def test_now_without_parens_returns_datetime(self):
        from datetime import datetime
        val = self._parse('NOW()')
        self.assertIsInstance(val, datetime)

    def test_unknown_function_call_returns_none(self):
        # Joomla: `DATE_FORMAT(...)`. We can't meaningfully evaluate
        # it, so we surface None and let the field default fill in.
        self.assertIsNone(self._parse("DATE_FORMAT(NULL, '%Y-%m-%d')"))

    def test_installer_placeholder_returns_none(self):
        # Dolibarr: `__ENTITY__` is substituted at install time.
        self.assertIsNone(self._parse('__ENTITY__'))
        self.assertIsNone(self._parse('__DEPLOY_ID__'))

    def test_version_gated_inner_value(self):
        # Sakila: `/*!50705 0x... */` wraps a BLOB in a version gate.
        val, _ = _parse_value("/*!50705 0xDEAD */", 0)
        self.assertEqual(val, b'\xde\xad')

"""Tests for datalift.management.commands.ingestdump.

Covers the pure-Python helpers (coercion, column-order extraction,
default-model-name) plus behavioural tests that the bulk_load
fallback path isolates failing rows under ``--continue-on-error``.

Run via:
    venv/bin/python manage.py test datalift.tests.test_ingestdump
"""

from django.test import SimpleTestCase

from datalift.management.commands.ingestdump import (
    _apply_value_map,
    _bulk_load,
    _coerce_binary_value,
    _coerce_date_string,
    _default_model_name,
    _dedupe_rows,
    _extract_column_order,
)


class ExtractColumnOrderTests(SimpleTestCase):
    """Pulls column names in order out of a CREATE TABLE DDL block,
    used when the INSERT doesn't specify its own column list."""

    def test_plain(self):
        ddl = """CREATE TABLE users (
            id int,
            name varchar(64),
            email varchar(120)
        )"""
        self.assertEqual(
            _extract_column_order(ddl),
            ['id', 'name', 'email'],
        )

    def test_fulltext_column_is_a_column_not_constraint(self):
        # Pagila regression — see test_model_generator for the
        # matching parse_create_table test.
        ddl = """CREATE TABLE film (
            film_id int NOT NULL,
            fulltext tsvector NOT NULL
        )"""
        self.assertEqual(
            _extract_column_order(ddl),
            ['film_id', 'fulltext'],
        )

    def test_constraint_lines_are_skipped(self):
        ddl = """CREATE TABLE dept_emp (
            emp_no INT NOT NULL,
            dept_no CHAR(4) NOT NULL,
            PRIMARY KEY (emp_no, dept_no),
            KEY dept_idx (dept_no),
            FOREIGN KEY (emp_no) REFERENCES employees (emp_no)
        )"""
        self.assertEqual(
            _extract_column_order(ddl),
            ['emp_no', 'dept_no'],
        )

    def test_inline_comment_with_nested_parens_survives(self):
        # Sanity: column-level COMMENT 'foo (bar)' shouldn't throw
        # the depth counter off.
        ddl = """CREATE TABLE t (
            id int NOT NULL COMMENT 'primary (auto)',
            tag varchar(32)
        )"""
        self.assertEqual(
            _extract_column_order(ddl),
            ['id', 'tag'],
        )


class DefaultModelNameTests(SimpleTestCase):
    """Mirrors model_generator.table_to_model_name's basic shape so
    ingestdump can resolve tables without a map entry."""

    def test_snake_to_pascal(self):
        self.assertEqual(_default_model_name('app', 'user_group'), 'UserGroup')

    def test_strips_app_label_prefix(self):
        self.assertEqual(_default_model_name('lab', 'lab_baby'), 'Baby')

    def test_multiword_preserved(self):
        # `_default_model_name` doesn't singularize — that would
        # cause collisions with model_generator's full
        # `table_to_model_name` which does. Staying naïve here
        # means an unmapped `categories` table resolves to
        # `Categories`, matching the class that genmodels would
        # have emitted if nothing singularized (and if it did
        # singularize, the explicit map entry would disambiguate).
        self.assertEqual(
            _default_model_name('app', 'news_items'),
            'NewsItems',
        )


class ApplyValueMapTests(SimpleTestCase):
    def test_pass_through_none(self):
        self.assertIsNone(_apply_value_map(None, {'M': 'male'}))

    def test_mapped_hit(self):
        self.assertEqual(_apply_value_map('M', {'M': 'male', 'F': 'female'}), 'male')

    def test_unmapped_returns_original(self):
        self.assertEqual(_apply_value_map('X', {'M': 'male'}), 'X')

    def test_default_sentinel(self):
        # The __default__ sentinel catches any unmapped value.
        vmap = {'M': 'male', '__default__': 'unknown'}
        self.assertEqual(_apply_value_map('X', vmap), 'unknown')


class CoerceBinaryValueTests(SimpleTestCase):
    """pg_dump emits bytea values as `'\\xhex…'` inside quoted
    strings; Django's BinaryField needs actual bytes."""

    def test_none_passes_through(self):
        self.assertIsNone(_coerce_binary_value(None))

    def test_bytes_pass_through(self):
        self.assertEqual(_coerce_binary_value(b'\x00\x01'), b'\x00\x01')

    def test_postgres_hex_escape(self):
        self.assertEqual(
            _coerce_binary_value(r'\x89504e47'),
            b'\x89\x50\x4e\x47',
        )

    def test_plain_text_encodes_as_utf8(self):
        self.assertEqual(_coerce_binary_value('hello'), b'hello')


class CoerceDateStringTests(SimpleTestCase):
    """Chinook stores dates as ``YYYY/M/D``; some EU dumps use
    ``DD-MM-YYYY``. Django's DateTimeField.to_python refuses
    anything that isn't ISO-like."""

    def test_already_iso(self):
        self.assertEqual(
            _coerce_date_string('2002-08-14'),
            '2002-08-14',
        )

    def test_slash_separated(self):
        # Chinook: Employee hire_date = '2002/8/14'.
        result = _coerce_date_string('2002/8/14')
        self.assertTrue(result.startswith('2002-08-14'))

    def test_european_dash(self):
        result = _coerce_date_string('14-08-2002')
        self.assertTrue(result.startswith('2002-08-14'))

    def test_compact(self):
        result = _coerce_date_string('20020814')
        self.assertTrue(result.startswith('2002-08-14'))

    def test_unparseable_passes_through(self):
        # If no format matches, return the value unchanged so the
        # caller sees a clean ValidationError.
        self.assertEqual(
            _coerce_date_string('not a date'),
            'not a date',
        )

    def test_none_passes_through(self):
        self.assertIsNone(_coerce_date_string(None))

    def test_non_string_passes_through(self):
        import datetime as dt
        d = dt.date(2026, 4, 24)
        self.assertIs(_coerce_date_string(d), d)


class DedupeRowsTests(SimpleTestCase):
    """The map's ``dedupe_by`` spec collapses duplicates on a given
    field. Used for the Babybase case where two user rows share an
    email address and the port picks one."""

    class _R:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    def test_simple_dedupe(self):
        objs = [
            self._R(email='a@x.com', name='A'),
            self._R(email='b@x.com', name='B'),
            self._R(email='a@x.com', name='A-duplicate'),
        ]
        captured = []
        result, dropped_count = _dedupe_rows(
            objs, 'email', captured.append,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(dropped_count, 1)
        self.assertEqual({r.email for r in result}, {'a@x.com', 'b@x.com'})


class BulkLoadTests(SimpleTestCase):
    """``_bulk_load`` is the fast/slow-path wrapper around
    bulk_create. It owns the fast-fail vs continue-on-error
    behaviour."""

    class _GoodObj:
        def save(self, *a, **kw):
            pass

    class _BadObj:
        def __init__(self, msg='bulk rejects this'):
            self._msg = msg

        def save(self, *a, **kw):
            raise ValueError(self._msg)

    class _GoodModel:
        class objects:
            @staticmethod
            def bulk_create(objs, batch_size=None):
                return objs

    class _AlwaysFailsBulkModel:
        class objects:
            @staticmethod
            def bulk_create(objs, batch_size=None):
                raise RuntimeError('synthetic batch failure')

    def test_empty_returns_zero(self):
        inserted, errors = _bulk_load(self._GoodModel, [], 500)
        self.assertEqual(inserted, 0)
        self.assertEqual(errors, [])

    def test_happy_path_single_batch(self):
        objs = [self._GoodObj() for _ in range(3)]
        inserted, errors = _bulk_load(self._GoodModel, objs, 500)
        self.assertEqual(inserted, 3)
        self.assertEqual(errors, [])

    def test_fast_fail_raises_without_flag(self):
        # Default: preserve pre-existing behaviour — any batch
        # exception blows the whole ingest.
        with self.assertRaises(RuntimeError):
            _bulk_load(
                self._AlwaysFailsBulkModel,
                [self._GoodObj()],
                500,
                continue_on_error=False,
            )

    def test_continue_on_error_isolates_bad_rows(self):
        # The bulk path fails. The row-by-row fallback finds the
        # single bad row, reports it with a short message, and lets
        # the good rows through.
        objs = [
            self._GoodObj(),
            self._BadObj('syntetic row error'),
            self._GoodObj(),
        ]
        inserted, errors = _bulk_load(
            self._AlwaysFailsBulkModel,
            objs,
            500,
            continue_on_error=True,
        )
        self.assertEqual(inserted, 2)
        self.assertEqual(len(errors), 1)
        idx, msg = errors[0]
        self.assertEqual(idx, 2)  # 1-based
        self.assertIn('syntetic row error', msg)

    def test_continue_on_error_all_bad(self):
        objs = [self._BadObj('err {}'.format(i)) for i in range(3)]
        inserted, errors = _bulk_load(
            self._AlwaysFailsBulkModel,
            objs,
            500,
            continue_on_error=True,
        )
        self.assertEqual(inserted, 0)
        self.assertEqual([idx for idx, _ in errors], [1, 2, 3])

    def test_error_message_is_truncated(self):
        long_msg = 'x' * 500
        objs = [self._BadObj(long_msg)]
        _, errors = _bulk_load(
            self._AlwaysFailsBulkModel,
            objs,
            500,
            continue_on_error=True,
        )
        _, msg = errors[0]
        self.assertLessEqual(len(msg), 160)

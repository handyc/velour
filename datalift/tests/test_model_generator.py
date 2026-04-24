"""Regression tests for datalift.model_generator.

Each test covers one or more historical bugs with a minimal inline
schema. The source corpus is named in the test docstring.

Run via:
    venv/bin/python manage.py test datalift.tests.test_model_generator
"""

from django.test import SimpleTestCase

from datalift.model_generator import (
    _common_table_prefix,
    _normalize_type,
    _type_keyword,
    column_to_field_name,
    generate_models_py,
    infer_field,
    parse_create_table,
    parse_dump,
    singularize,
    table_to_model_name,
)


class TypeNormalizationTests(SimpleTestCase):
    """`_normalize_type` lowercases the keyword + modifiers but
    preserves the parenthesised argument list — ENUM values and
    CHAR length specifiers both depend on this."""

    def test_enum_preserves_case(self):
        # Employees regression: `ENUM('M','F')` was being fully
        # lowercased, so TextChoices saw `m`/`f` and downstream
        # data comparisons silently failed.
        self.assertEqual(
            _normalize_type("ENUM('M','F')"),
            "enum('M','F')",
        )

    def test_enum_with_space_between_keyword_and_paren(self):
        self.assertEqual(
            _normalize_type("ENUM ('M','F')"),
            "enum('M','F')",
        )

    def test_varchar_normalizes_keyword_only(self):
        self.assertEqual(_normalize_type('VARCHAR(255)'), 'varchar(255)')

    def test_int_unsigned(self):
        self.assertEqual(_normalize_type('INT UNSIGNED'), 'int unsigned')


class TypeKeywordExtractionTests(SimpleTestCase):
    def test_bare_keyword(self):
        self.assertEqual(_type_keyword('int'), 'int')

    def test_with_args(self):
        self.assertEqual(_type_keyword('varchar(255)'), 'varchar')

    def test_with_modifier(self):
        self.assertEqual(_type_keyword('int unsigned'), 'int')


class InferFieldTests(SimpleTestCase):
    """`infer_field` maps SQL types onto Django field declarations
    via the type registry."""

    def _col(self, raw_type, **kwargs):
        from datalift.model_generator import Column
        defaults = dict(name='c', raw_type=raw_type, not_null=False,
                        default=None, is_auto_inc=False,
                        is_primary=False, is_unique=False,
                        on_update_current_ts=False)
        defaults.update(kwargs)
        return Column(**defaults)

    def test_nvarchar_maps_to_charfield(self):
        # Chinook: NVARCHAR(160) was falling through to TextField.
        self.assertIn('CharField', infer_field(self._col('nvarchar(160)')))
        self.assertIn('max_length=160', infer_field(self._col('nvarchar(160)')))

    def test_numeric_maps_to_decimal(self):
        # Chinook: NUMERIC(10,2) was falling through to TextField.
        result = infer_field(self._col('numeric(10,2)'))
        self.assertIn('DecimalField', result)
        self.assertIn('max_digits=10', result)
        self.assertIn('decimal_places=2', result)

    def test_decimal_still_works(self):
        result = infer_field(self._col('decimal(12,4)'))
        self.assertIn('DecimalField', result)
        self.assertIn('max_digits=12', result)

    def test_postgres_timestamp_with_tz(self):
        # Pagila: `timestamp with time zone` — the raw_type
        # normalisation leaves it as `timestamp` keyword, which
        # should still hit DateTimeField.
        col = self._col(_normalize_type('timestamp with time zone'))
        self.assertIn('DateTimeField', infer_field(col))

    def test_tinyint_1_is_boolean(self):
        # Classic MySQL bool shape.
        self.assertIn('BooleanField', infer_field(self._col('tinyint(1)')))

    def test_tinyint_n_is_smallint(self):
        # Pagila / general: plain `smallint` isn't the MySQL
        # bool shape, so stays numeric.
        self.assertIn('SmallInteger', infer_field(self._col('smallint')))

    def test_bigint_unsigned_goes_positive(self):
        # MediaWiki: BIGINT UNSIGNED AUTO_INCREMENT. When not
        # auto-inc, should be PositiveBigInteger.
        result = infer_field(self._col('bigint unsigned'))
        self.assertIn('PositiveBigInteger', result)

    def test_bytea_maps_to_binary(self):
        # Pagila: `picture bytea`.
        self.assertIn('BinaryField', infer_field(self._col('bytea')))

    def test_uuid_maps_to_uuid_field(self):
        self.assertIn('UUIDField', infer_field(self._col('uuid')))

    def test_json_maps_to_json_field(self):
        self.assertIn('JSONField', infer_field(self._col('json')))

    def test_auto_inc_is_bigautofield(self):
        col = self._col('int', is_auto_inc=True)
        self.assertIn('BigAutoField', infer_field(col))
        self.assertIn('primary_key=True', infer_field(col))

    def test_default_propagates_to_integer(self):
        # Joomla regression: NOT NULL DEFAULT 0 on an int column
        # was being silently dropped; then an INSERT that omitted
        # the column tripped the NOT NULL check.
        col = self._col('int', default='0', not_null=True)
        self.assertIn('default=0', infer_field(col))

    def test_quoted_numeric_default_unquoted_in_django(self):
        # Legacy schemas often write `DEFAULT '0'` (quoted) even
        # for an int column. Django wants a python int default.
        col = self._col('int', default="'0'", not_null=True)
        self.assertIn('default=0', infer_field(col))


class TableToModelNameTests(SimpleTestCase):
    def test_snake_to_pascal(self):
        self.assertEqual(
            table_to_model_name(
                'dept_manager', 'hrapp',
                ['dept_manager', 'employees', 'salaries'],
            ),
            'DeptManager',
        )

    def test_camelcase_is_preserved(self):
        # Chinook: `InvoiceLine` → was being squashed to
        # `Invoiceline` by `.capitalize()`.
        self.assertEqual(
            table_to_model_name(
                'InvoiceLine', 'store',
                ['InvoiceLine', 'Track', 'Artist'],
            ),
            'InvoiceLine',
        )

    def test_mediatype_preserves_case(self):
        self.assertEqual(
            table_to_model_name(
                'MediaType', 'store', ['MediaType', 'Track'],
            ),
            'MediaType',
        )

    def test_app_label_prefix_strip_when_all_tables_match(self):
        # Babybase: `lab_user`, `lab_baby` under --app lab →
        # strip the lab_ prefix.
        self.assertEqual(
            table_to_model_name(
                'lab_user', 'lab', ['lab_user', 'lab_baby'],
            ),
            'User',
        )

    def test_app_label_prefix_kept_when_some_tables_do_not_match(self):
        # PrestaShop: --app shop but only SOME tables start with
        # `shop_` — DON'T strip or `shop_group` collapses to
        # `Group` and collides with a distinct `group` table.
        self.assertEqual(
            table_to_model_name(
                'shop_group', 'shop',
                ['shop_group', 'group', 'product'],
            ),
            'ShopGroup',
        )

    def test_common_prefix_auto_strip(self):
        # Dolibarr: every table starts with `llx_`, operator
        # didn't pass --app llx. Auto-detected common prefix gets
        # stripped.
        self.assertEqual(
            table_to_model_name(
                'llx_societe', 'erp',
                ['llx_societe', 'llx_user', 'llx_invoice'],
            ),
            'Societe',
        )

    def test_common_prefix_detection(self):
        self.assertEqual(
            _common_table_prefix(['mybb_users', 'mybb_posts', 'mybb_threads']),
            'mybb_',
        )
        # Mixed — no common prefix.
        self.assertEqual(
            _common_table_prefix(['users', 'shop_group', 'posts']),
            '',
        )


class SingularizeTests(SimpleTestCase):
    def test_regular_plural(self):
        self.assertEqual(singularize('users'), 'user')

    def test_ies_plural(self):
        self.assertEqual(singularize('categories'), 'category')

    def test_preserves_mixed_case(self):
        # Chinook: `InvoiceLines` → `InvoiceLine`, not `invoiceline`.
        self.assertEqual(singularize('InvoiceLines'), 'InvoiceLine')

    def test_irregular(self):
        self.assertEqual(singularize('people'), 'person')
        self.assertEqual(singularize('children'), 'child')


class ParseCreateTableTests(SimpleTestCase):
    def test_natural_primary_key(self):
        # Employees: PRIMARY KEY (emp_no) on a non-auto-inc column
        # used to be silently dropped; natural_pk detection needs
        # to fire.
        t = parse_create_table("""
            CREATE TABLE employees (
                emp_no INT NOT NULL,
                birth_date DATE NOT NULL,
                PRIMARY KEY (emp_no)
            )
        """)
        self.assertEqual(t.primary_key, ['emp_no'])

    def test_inline_primary_key_on_column(self):
        # Dolibarr: `id smallint PRIMARY KEY` inline.
        t = parse_create_table("""
            CREATE TABLE foo (
                id smallint PRIMARY KEY,
                name varchar(64)
            )
        """)
        self.assertEqual(t.primary_key, ['id'])

    def test_composite_primary_key(self):
        # Joomla's `associations` etc.
        t = parse_create_table("""
            CREATE TABLE j (
                context varchar(50),
                id int,
                PRIMARY KEY (context, id)
            )
        """)
        self.assertEqual(t.primary_key, ['context', 'id'])

    def test_fulltext_is_a_valid_column_name(self):
        # Pagila: `fulltext tsvector NOT NULL`. Was previously
        # misclassified as a FULLTEXT KEY constraint line.
        t = parse_create_table("""
            CREATE TABLE film (
                film_id int NOT NULL,
                fulltext tsvector NOT NULL
            )
        """)
        col_names = [c.name for c in t.columns]
        self.assertIn('fulltext', col_names)
        self.assertEqual(len(t.columns), 2)

    def test_inline_fk_on_delete_cascade(self):
        # Employees: classic `FOREIGN KEY (x) REFERENCES t (x)
        # ON DELETE CASCADE` inline. Plus ON UPDATE interleaving.
        t = parse_create_table("""
            CREATE TABLE dept_emp (
                emp_no INT NOT NULL,
                dept_no CHAR(4) NOT NULL,
                FOREIGN KEY (emp_no) REFERENCES employees (emp_no) ON UPDATE RESTRICT ON DELETE CASCADE,
                FOREIGN KEY (dept_no) REFERENCES departments (dept_no) ON DELETE CASCADE,
                PRIMARY KEY (emp_no, dept_no)
            )
        """)
        self.assertEqual(len(t.foreign_keys), 2)
        ondels = {fk.on_delete for fk in t.foreign_keys}
        self.assertEqual(ondels, {'CASCADE'})


class ParseDumpTests(SimpleTestCase):
    """End-to-end parse_dump behaviour — includes duplicate
    handling + ALTER TABLE post-pass."""

    def test_duplicate_create_table_is_last_wins(self):
        # WordPress regression: users table was defined twice
        # (single-site + multisite), producing two `class User`.
        sql = """
            CREATE TABLE users (id INT, name VARCHAR(60));
            CREATE TABLE users (id INT, name VARCHAR(60), spam TINYINT(1));
        """
        tables = parse_dump(sql)
        self.assertEqual(len(tables), 1)
        # Last one (with spam column) wins.
        col_names = {c.name for c in tables[0].columns}
        self.assertIn('spam', col_names)

    def test_alter_table_fk_picked_up(self):
        # Chinook: FKs declared via separate ALTER TABLE.
        sql = """
            CREATE TABLE Invoice (InvoiceId INT NOT NULL);
            CREATE TABLE Customer (CustomerId INT NOT NULL);
            ALTER TABLE Invoice ADD CONSTRAINT FK_I
                FOREIGN KEY (CustomerId) REFERENCES Customer (CustomerId)
                ON DELETE NO ACTION ON UPDATE NO ACTION;
        """
        tables = parse_dump(sql)
        invoice = next(t for t in tables if t.name == 'Invoice')
        self.assertEqual(len(invoice.foreign_keys), 1)
        self.assertEqual(invoice.foreign_keys[0].ref_table, 'Customer')

    def test_alter_table_primary_key_picked_up(self):
        # Pagila: PKs declared via separate ALTER TABLE.
        sql = """
            CREATE TABLE customer (customer_id integer NOT NULL);
            ALTER TABLE ONLY public.customer
                ADD CONSTRAINT customer_pkey PRIMARY KEY (customer_id);
        """
        tables = parse_dump(sql)
        self.assertEqual(tables[0].primary_key, ['customer_id'])

    def test_alter_table_pk_mysql_permissive_syntax(self):
        # Dolibarr: `ADD PRIMARY KEY pk_name (cols)` — constraint
        # name AFTER the PK keyword.
        sql = """
            CREATE TABLE llx_rights_def (
                id integer NOT NULL,
                entity integer DEFAULT 1 NOT NULL
            );
            ALTER TABLE llx_rights_def ADD PRIMARY KEY pk_rights_def (id, entity);
        """
        tables = parse_dump(sql)
        self.assertEqual(tables[0].primary_key, ['id', 'entity'])

    def test_nextval_default_promotes_to_auto_inc(self):
        # Pagila: `DEFAULT nextval('foo_seq'::regclass)` means
        # auto-increment. Combined with the ALTER TABLE PK, the
        # column should end up as is_auto_inc=True.
        sql = """
            CREATE TABLE customer (
                customer_id integer DEFAULT nextval('public.customer_customer_id_seq'::regclass) NOT NULL
            );
            ALTER TABLE ONLY public.customer
                ADD CONSTRAINT customer_pkey PRIMARY KEY (customer_id);
        """
        tables = parse_dump(sql)
        pk_col = next(c for c in tables[0].columns if c.name == 'customer_id')
        self.assertTrue(pk_col.is_auto_inc)

    def test_apostrophe_in_comment_preserves_table_count(self):
        # Dolibarr regression repro at the parse_dump level.
        sql = """
            CREATE TABLE first (id INT);
            -- Defini les types de contact d'un element
            CREATE TABLE second (id INT);
            CREATE TABLE third (id INT);
        """
        self.assertEqual([t.name for t in parse_dump(sql)],
                         ['first', 'second', 'third'])


class GenerateModelsPyTests(SimpleTestCase):
    """End-to-end models.py generation — emitter behaviour."""

    def test_natural_pk_gets_primary_key_true(self):
        # Employees: natural PK on non-auto-inc column must be
        # promoted to `primary_key=True`.
        tables = parse_dump("""
            CREATE TABLE employees (
                emp_no INT NOT NULL,
                PRIMARY KEY (emp_no)
            );
        """)
        out = generate_models_py(tables, app_label='hrapp')
        self.assertIn('emp_no = models.IntegerField(primary_key=True)', out)

    def test_natural_pk_strips_null_blank(self):
        # PrestaShop: `smarty_last_flush` has an ENUM PK without
        # explicit NOT NULL. Django rejects `primary_key=True` +
        # `null=True`.
        tables = parse_dump("""
            CREATE TABLE smarty_last_flush (
                type ENUM('compile', 'template'),
                PRIMARY KEY (type)
            );
        """)
        out = generate_models_py(tables, app_label='shop')
        # Find the type line.
        type_line = next(
            line for line in out.splitlines() if line.strip().startswith('type =')
        )
        self.assertIn('primary_key=True', type_line)
        self.assertNotIn('null=True', type_line)

    def test_composite_pk_id_column_becomes_primary_key(self):
        # Joomla: `associations` has composite PK (context, id)
        # — the `id` column must get primary_key=True to satisfy
        # Django's E004, and the UniqueConstraint covers the
        # composite semantic.
        tables = parse_dump("""
            CREATE TABLE associations (
                context varchar(50),
                id int,
                PRIMARY KEY (context, id)
            );
        """)
        out = generate_models_py(tables, app_label='joomla_app')
        self.assertIn('id = models.IntegerField(primary_key=True)', out)
        self.assertIn('UniqueConstraint', out)

    def test_mediawiki_prefix_placeholder_produces_clean_class(self):
        tables = parse_dump("""
            CREATE TABLE /*_*/actor (
                actor_id BIGINT UNSIGNED AUTO_INCREMENT NOT NULL,
                actor_name VARBINARY(255) NOT NULL,
                PRIMARY KEY(actor_id)
            );
        """)
        out = generate_models_py(tables, app_label='wiki')
        self.assertIn('class Actor(', out)
        self.assertIn("db_table = 'actor'", out)

    def test_wordpress_prefix_placeholder_produces_clean_class(self):
        tables = parse_dump("""
            CREATE TABLE $wpdb->users (
                ID bigint(20) unsigned NOT NULL auto_increment,
                user_login varchar(60) NOT NULL default '',
                PRIMARY KEY (ID)
            );
        """)
        out = generate_models_py(tables, app_label='wp')
        self.assertIn('class User(', out)
        self.assertIn("db_table = 'users'", out)

    def test_chinook_alter_table_fk_emits_foreignkey(self):
        tables = parse_dump("""
            CREATE TABLE Customer (
                CustomerId INT NOT NULL,
                CONSTRAINT PK_Customer PRIMARY KEY (CustomerId)
            );
            CREATE TABLE Invoice (
                InvoiceId INT NOT NULL,
                CustomerId INT NOT NULL,
                CONSTRAINT PK_Invoice PRIMARY KEY (InvoiceId)
            );
            ALTER TABLE Invoice ADD CONSTRAINT FK_I
                FOREIGN KEY (CustomerId) REFERENCES Customer (CustomerId);
        """)
        out = generate_models_py(tables, app_label='store')
        self.assertIn('class Invoice(', out)
        self.assertIn('ForeignKey("Customer"', out)

    def test_non_pk_fk_target_emits_to_field(self):
        # Dolibarr: `fk_pcg_version → llx_accounting_system(pcg_version)`
        # references a non-PK VARCHAR.
        tables = parse_dump("""
            CREATE TABLE accounting_system (
                rowid integer AUTO_INCREMENT PRIMARY KEY,
                pcg_version varchar(32) NOT NULL,
                label varchar(255)
            );
            CREATE TABLE accounting_account (
                rowid integer AUTO_INCREMENT PRIMARY KEY,
                fk_pcg_version varchar(32) NOT NULL
            );
            ALTER TABLE accounting_account
                ADD CONSTRAINT fk_foo FOREIGN KEY (fk_pcg_version)
                REFERENCES accounting_system (pcg_version);
        """)
        out = generate_models_py(tables, app_label='erp')
        self.assertIn("to_field='pcg_version'", out)
        # Target column must be unique to satisfy Django's E311.
        self.assertIn('unique=True', out)

    def test_fk_column_routes_via_attname(self):
        # Models emit FKs that Django treats as owning a
        # `<name>_id` attname. This test just checks the model
        # shape — attname routing is actually tested in
        # test_ingestdump.
        tables = parse_dump("""
            CREATE TABLE t (id INT AUTO_INCREMENT PRIMARY KEY);
            CREATE TABLE r (
                t_id INT,
                FOREIGN KEY (t_id) REFERENCES t (id)
            );
        """)
        out = generate_models_py(tables, app_label='x')
        self.assertIn('ForeignKey', out)

    def test_field_name_id_reserved_collision(self):
        # Joomla: composite PK including `id`. Django reserves
        # the bare name `id` for primary keys, so if it's in the
        # composite it MUST carry primary_key=True.
        tables = parse_dump("""
            CREATE TABLE a (
                context varchar(50),
                id int,
                PRIMARY KEY (context, id)
            );
        """)
        out = generate_models_py(tables, app_label='a')
        id_line = next(
            line for line in out.splitlines()
            if line.strip().startswith('id = ')
        )
        self.assertIn('primary_key=True', id_line)

    def test_ambiguous_app_label_does_not_strip_prefix(self):
        # PrestaShop: prevent `shop_group` → `Group` collision
        # with a real `group` table.
        tables = parse_dump("""
            CREATE TABLE `group` (id int AUTO_INCREMENT PRIMARY KEY);
            CREATE TABLE shop_group (id int AUTO_INCREMENT PRIMARY KEY);
        """)
        out = generate_models_py(tables, app_label='shop')
        # Both classes present, no collision.
        self.assertIn('class Group(', out)
        self.assertIn('class ShopGroup(', out)


class ColumnToFieldNameTests(SimpleTestCase):
    def test_camel_to_snake(self):
        self.assertEqual(column_to_field_name('userName'), 'user_name')

    def test_preserve_runs_of_caps(self):
        self.assertEqual(column_to_field_name('IPAddress'), 'ip_address')

    def test_python_keyword_is_suffixed(self):
        # Column literally named `class` — Python-reserved. We
        # append `_field` rather than the PEP 8 `_` suffix so the
        # name reads as unmistakeably renamed in a reviewer's diff.
        self.assertEqual(column_to_field_name('class'), 'class_field')

    def test_leading_digit_prefixed(self):
        self.assertEqual(column_to_field_name('3d_model'), 'f_3d_model')

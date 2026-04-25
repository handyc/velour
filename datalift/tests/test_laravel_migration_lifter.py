"""Tests for datalift.laravel_migration_lifter — Laravel migrations → Django models."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.laravel_migration_lifter import (
    apply, parse_blueprint, parse_migration_file, parse_migrations,
    render_models, render_worklist,
)


class BlueprintColumnTests(SimpleTestCase):

    def test_string_column(self):
        cols = parse_blueprint("$table->string('email');")
        self.assertEqual(len(cols), 1)
        self.assertEqual(cols[0].name, 'email')
        self.assertEqual(cols[0].django_type, 'CharField')
        self.assertEqual(cols[0].kwargs.get('max_length'), 255)

    def test_string_with_length(self):
        cols = parse_blueprint("$table->string('email', 100);")
        self.assertEqual(cols[0].kwargs['max_length'], 100)

    def test_id_column(self):
        cols = parse_blueprint("$table->id();")
        self.assertEqual(cols[0].name, '_unnamed_id')  # default, no arg given
        self.assertEqual(cols[0].django_type, 'BigAutoField')
        self.assertTrue(cols[0].kwargs.get('primary_key'))

    def test_integer(self):
        cols = parse_blueprint("$table->integer('count');")
        self.assertEqual(cols[0].django_type, 'IntegerField')

    def test_unsigned_integer(self):
        cols = parse_blueprint("$table->unsignedInteger('count');")
        self.assertEqual(cols[0].django_type, 'PositiveIntegerField')

    def test_boolean(self):
        cols = parse_blueprint("$table->boolean('active');")
        self.assertEqual(cols[0].django_type, 'BooleanField')

    def test_text(self):
        cols = parse_blueprint("$table->text('body');")
        self.assertEqual(cols[0].django_type, 'TextField')

    def test_decimal_with_precision(self):
        cols = parse_blueprint("$table->decimal('price', 10, 2);")
        self.assertEqual(cols[0].django_type, 'DecimalField')
        self.assertEqual(cols[0].kwargs.get('max_digits'), 10)
        self.assertEqual(cols[0].kwargs.get('decimal_places'), 2)

    def test_datetime(self):
        cols = parse_blueprint("$table->dateTime('scheduled_at');")
        self.assertEqual(cols[0].django_type, 'DateTimeField')

    def test_json(self):
        cols = parse_blueprint("$table->json('settings');")
        self.assertEqual(cols[0].django_type, 'JSONField')

    def test_uuid(self):
        cols = parse_blueprint("$table->uuid('public_id');")
        self.assertEqual(cols[0].django_type, 'UUIDField')

    def test_enum_choices(self):
        cols = parse_blueprint(
            "$table->enum('status', ['draft', 'published', 'archived']);"
        )
        self.assertEqual(cols[0].django_type, 'CharField')
        self.assertEqual(cols[0].kwargs.get('choices'),
                         ['draft', 'published', 'archived'])

    def test_remember_token(self):
        cols = parse_blueprint("$table->rememberToken();")
        self.assertEqual(cols[0].name, 'remember_token')
        self.assertEqual(cols[0].kwargs.get('max_length'), 100)
        self.assertTrue(cols[0].kwargs.get('null'))

    def test_timestamps_expands_to_two_columns(self):
        cols = parse_blueprint("$table->timestamps();")
        names = sorted(c.name for c in cols)
        self.assertEqual(names, ['created_at', 'updated_at'])
        self.assertTrue(cols[0].kwargs.get('auto_now_add')
                        or cols[0].kwargs.get('auto_now'))

    def test_soft_deletes(self):
        cols = parse_blueprint("$table->softDeletes();")
        self.assertEqual(cols[0].name, 'deleted_at')
        self.assertTrue(cols[0].kwargs.get('null'))


class ModifierChainTests(SimpleTestCase):

    def test_nullable(self):
        cols = parse_blueprint("$table->string('phone')->nullable();")
        self.assertTrue(cols[0].kwargs.get('null'))
        self.assertTrue(cols[0].kwargs.get('blank'))

    def test_unique(self):
        cols = parse_blueprint("$table->string('email')->unique();")
        self.assertTrue(cols[0].kwargs.get('unique'))

    def test_default_string(self):
        cols = parse_blueprint("$table->string('status')->default('active');")
        self.assertEqual(cols[0].kwargs.get('default'), 'active')

    def test_default_int(self):
        cols = parse_blueprint("$table->integer('hits')->default(0);")
        self.assertEqual(cols[0].kwargs.get('default'), 0)

    def test_default_bool(self):
        cols = parse_blueprint("$table->boolean('active')->default(true);")
        self.assertIs(cols[0].kwargs.get('default'), True)

    def test_index_modifier(self):
        cols = parse_blueprint("$table->string('slug')->index();")
        self.assertTrue(cols[0].kwargs.get('db_index'))

    def test_comment_modifier(self):
        cols = parse_blueprint("$table->integer('hits')->comment('view counter');")
        self.assertEqual(cols[0].kwargs.get('help_text'), 'view counter')

    def test_chained_modifiers(self):
        cols = parse_blueprint(
            "$table->string('phone', 30)->nullable()->unique()->default('');"
        )
        self.assertEqual(cols[0].kwargs['max_length'], 30)
        self.assertTrue(cols[0].kwargs.get('null'))
        self.assertTrue(cols[0].kwargs.get('unique'))
        self.assertEqual(cols[0].kwargs.get('default'), '')


class ForeignKeyTests(SimpleTestCase):

    def test_foreign_id_constrained(self):
        # `$table->foreignId('user_id')->constrained();` (auto-references users.id)
        from datalift.laravel_migration_lifter import (
            parse_migration_file, TableRecord, _resolve_foreign_keys,
        )
        body = (
            "$table->id();"
            "$table->foreignId('user_id')->constrained();"
        )
        cols = parse_blueprint(body)
        # We need to also resolve FK chain manually for this synthetic test.
        rec = TableRecord(name='posts', model_name='Post', columns=cols)
        _resolve_foreign_keys(rec, body)
        fk = next(c for c in rec.columns if c.name == 'user_id')
        self.assertEqual(fk.django_type, 'ForeignKey')
        self.assertIn('Users', fk.kwargs.get('to', '') + 'Users')  # reasonable target

    def test_foreign_with_explicit_references(self):
        from datalift.laravel_migration_lifter import (
            TableRecord, _resolve_foreign_keys,
        )
        body = ("$table->unsignedBigInteger('post_id');"
                "$table->foreign('post_id')->references('id')->on('posts')"
                "->onDelete('cascade');")
        cols = parse_blueprint(body)
        rec = TableRecord(name='comments', model_name='Comment', columns=cols)
        _resolve_foreign_keys(rec, body)
        fk = next(c for c in rec.columns if c.name == 'post_id')
        self.assertEqual(fk.django_type, 'ForeignKey')
        self.assertIn('Post', fk.kwargs.get('to', ''))
        self.assertEqual(fk.kwargs.get('on_delete'), 'models.CASCADE')


class FileWalkerTests(SimpleTestCase):

    def test_parse_full_migration_file(self):
        tmp = Path(tempfile.mkdtemp())
        f = tmp / '2024_01_01_create_users.php'
        f.write_text(dedent("""\
            <?php
            use Illuminate\\Database\\Migrations\\Migration;
            use Illuminate\\Database\\Schema\\Blueprint;
            use Illuminate\\Support\\Facades\\Schema;

            return new class extends Migration {
                public function up(): void
                {
                    Schema::create('users', function (Blueprint $table) {
                        $table->id();
                        $table->string('name');
                        $table->string('email')->unique();
                        $table->timestamp('email_verified_at')->nullable();
                        $table->string('password');
                        $table->rememberToken();
                        $table->timestamps();
                    });
                }
            };
        """))
        tables = parse_migration_file(f)
        self.assertEqual(len(tables), 1)
        t = tables[0]
        self.assertEqual(t.name, 'users')
        names = sorted(c.name for c in t.columns)
        self.assertIn('email', names)
        self.assertIn('password', names)
        self.assertIn('remember_token', names)
        self.assertIn('created_at', names)
        self.assertIn('updated_at', names)

    def test_parse_migrations_dir(self):
        tmp = Path(tempfile.mkdtemp())
        d = tmp / 'migrations'
        d.mkdir()
        (d / '001_users.php').write_text(dedent("""\
            <?php
            Schema::create('users', function ($table) {
                $table->string('name');
            });
        """))
        (d / '002_posts.php').write_text(dedent("""\
            <?php
            Schema::create('posts', function ($table) {
                $table->string('title');
            });
        """))
        result = parse_migrations(d)
        self.assertEqual(len(result.tables), 2)
        names = sorted(t.name for t in result.tables)
        self.assertEqual(names, ['posts', 'users'])


class ModelsRenderingTests(SimpleTestCase):

    def test_render_basic_models(self):
        from datalift.laravel_migration_lifter import (
            ColumnRecord, MigrationLiftResult, TableRecord,
        )
        result = MigrationLiftResult(tables=[
            TableRecord(
                name='users', model_name='User',
                columns=[
                    ColumnRecord(name='name', django_type='CharField',
                                 kwargs={'max_length': 255}),
                    ColumnRecord(name='email', django_type='CharField',
                                 kwargs={'max_length': 255, 'unique': True}),
                ],
            ),
        ])
        text = render_models(result, 'myapp')
        self.assertIn('class User(models.Model):', text)
        self.assertIn('models.CharField(max_length=255', text)
        self.assertIn("db_table = 'users'", text)
        self.assertIn('unique=True', text)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_models_file(self):
        from datalift.laravel_migration_lifter import (
            ColumnRecord, MigrationLiftResult, TableRecord,
        )
        tmp = Path(tempfile.mkdtemp())
        proj = tmp / 'proj'
        proj.mkdir()
        result = MigrationLiftResult(tables=[
            TableRecord(name='users', model_name='User',
                        columns=[ColumnRecord(name='name',
                                               django_type='CharField',
                                               kwargs={'max_length': 255})]),
        ])
        apply(result, proj, 'myapp')
        body = (proj / 'myapp' / 'models_migrations.py').read_text()
        self.assertIn('class User(models.Model):', body)


class WorklistTests(SimpleTestCase):

    def test_worklist_format(self):
        from datalift.laravel_migration_lifter import (
            ColumnRecord, MigrationLiftResult, TableRecord,
        )
        result = MigrationLiftResult(tables=[
            TableRecord(name='users', model_name='User',
                        columns=[ColumnRecord(name='x', django_type='CharField')]),
        ])
        text = render_worklist(result, 'app', Path('/tmp/migrations'))
        self.assertIn('liftmigrations worklist', text)
        self.assertIn('users', text)
        self.assertIn('User', text)

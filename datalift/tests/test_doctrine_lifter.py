"""Tests for datalift.doctrine_lifter — Doctrine entities → Django models."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.doctrine_lifter import (
    apply, parse_doctrine, parse_entity, render_models, render_worklist,
)


class EntityRecognitionTests(SimpleTestCase):

    def test_non_entity_returns_none(self):
        php = "<?php class JustAClass {}"
        self.assertIsNone(parse_entity(php))

    def test_entity_attribute_recognised(self):
        php = dedent("""\
            <?php
            #[ORM\\Entity]
            class Post {}
        """)
        ent = parse_entity(php)
        self.assertIsNotNone(ent)
        self.assertEqual(ent.class_name, 'Post')

    def test_table_name_from_attribute(self):
        php = dedent("""\
            <?php
            #[ORM\\Entity]
            #[ORM\\Table(name: 'blog_posts')]
            class Post {}
        """)
        ent = parse_entity(php)
        self.assertEqual(ent.db_table, 'blog_posts')

    def test_table_name_default_pluralised(self):
        php = "<?php\n#[ORM\\Entity]\nclass User {}\n"
        ent = parse_entity(php)
        self.assertEqual(ent.db_table, 'users')


class ColumnTranslationTests(SimpleTestCase):

    def _entity_for(self, body: str):
        php = dedent(f"""\
            <?php
            #[ORM\\Entity]
            class Post {{
            {body}
            }}
        """)
        return parse_entity(php)

    def test_string_column(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'string', length: 200)]\n"
            "    private string $title;\n"
        )
        col = next(c for c in ent.columns if c.name == 'title')
        self.assertEqual(col.django_type, 'CharField')
        self.assertEqual(col.kwargs.get('max_length'), 200)

    def test_text_column(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'text', nullable: true)]\n"
            "    private ?string $body = null;\n"
        )
        col = next(c for c in ent.columns if c.name == 'body')
        self.assertEqual(col.django_type, 'TextField')
        self.assertTrue(col.kwargs.get('null'))

    def test_integer(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'integer')]\n"
            "    private int $count;\n"
        )
        col = next(c for c in ent.columns if c.name == 'count')
        self.assertEqual(col.django_type, 'IntegerField')

    def test_boolean(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'boolean')]\n"
            "    private bool $active;\n"
        )
        col = next(c for c in ent.columns if c.name == 'active')
        self.assertEqual(col.django_type, 'BooleanField')

    def test_datetime(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'datetime')]\n"
            "    private \\DateTime $createdAt;\n"
        )
        col = next(c for c in ent.columns if c.name == 'created_at')
        self.assertEqual(col.django_type, 'DateTimeField')

    def test_decimal_with_precision(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'decimal', precision: 10, scale: 2)]\n"
            "    private string $price;\n"
        )
        col = next(c for c in ent.columns if c.name == 'price')
        self.assertEqual(col.django_type, 'DecimalField')
        self.assertEqual(col.kwargs.get('max_digits'), 10)
        self.assertEqual(col.kwargs.get('decimal_places'), 2)

    def test_id_with_generated_value(self):
        ent = self._entity_for(
            "    #[ORM\\Id]\n"
            "    #[ORM\\GeneratedValue]\n"
            "    #[ORM\\Column(type: 'integer')]\n"
            "    private int $id;\n"
        )
        col = next(c for c in ent.columns if c.name == 'id')
        self.assertEqual(col.django_type, 'AutoField')
        self.assertTrue(col.kwargs.get('primary_key'))

    def test_unique_field(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'string', unique: true)]\n"
            "    private string $email;\n"
        )
        col = next(c for c in ent.columns if c.name == 'email')
        self.assertTrue(col.kwargs.get('unique'))

    def test_camel_to_snake(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: 'datetime')]\n"
            "    private \\DateTime $publishedAt;\n"
        )
        col = next(c for c in ent.columns if c.name == 'published_at')
        self.assertEqual(col.django_type, 'DateTimeField')

    def test_type_inferred_from_php_hint_datetime_immutable(self):
        ent = self._entity_for(
            "    #[ORM\\Column]\n"
            "    private \\DateTimeImmutable $publishedAt;\n"
        )
        col = next(c for c in ent.columns if c.name == 'published_at')
        self.assertEqual(col.django_type, 'DateTimeField')

    def test_type_inferred_from_php_hint_int(self):
        ent = self._entity_for(
            "    #[ORM\\Column]\n"
            "    private int $views;\n"
        )
        col = next(c for c in ent.columns if c.name == 'views')
        self.assertEqual(col.django_type, 'IntegerField')

    def test_type_inferred_from_nullable_hint(self):
        ent = self._entity_for(
            "    #[ORM\\Column(nullable: true)]\n"
            "    private ?bool $featured = null;\n"
        )
        col = next(c for c in ent.columns if c.name == 'featured')
        self.assertEqual(col.django_type, 'BooleanField')
        self.assertTrue(col.kwargs.get('null'))

    def test_types_const_resolved(self):
        ent = self._entity_for(
            "    #[ORM\\Column(type: Types::DATETIME_MUTABLE)]\n"
            "    private \\DateTime $createdAt;\n"
        )
        col = next(c for c in ent.columns if c.name == 'created_at')
        self.assertEqual(col.django_type, 'DateTimeField')


class RelationshipTests(SimpleTestCase):

    def _entity_for(self, body: str):
        php = dedent(f"""\
            <?php
            #[ORM\\Entity]
            class Post {{
            {body}
            }}
        """)
        return parse_entity(php)

    def test_many_to_one_becomes_foreignkey(self):
        ent = self._entity_for(
            "    #[ORM\\ManyToOne(targetEntity: User::class)]\n"
            "    #[ORM\\JoinColumn(nullable: false)]\n"
            "    private User $author;\n"
        )
        col = next(c for c in ent.columns if c.name == 'author')
        self.assertEqual(col.django_type, 'ForeignKey')
        self.assertIn('User', col.kwargs.get('to', ''))

    def test_many_to_one_nullable(self):
        ent = self._entity_for(
            "    #[ORM\\ManyToOne(targetEntity: User::class)]\n"
            "    #[ORM\\JoinColumn(nullable: true)]\n"
            "    private ?User $editor;\n"
        )
        col = next(c for c in ent.columns if c.name == 'editor')
        self.assertTrue(col.kwargs.get('null'))

    def test_many_to_one_cascade(self):
        ent = self._entity_for(
            "    #[ORM\\ManyToOne(targetEntity: User::class)]\n"
            "    #[ORM\\JoinColumn(onDelete: 'CASCADE')]\n"
            "    private User $owner;\n"
        )
        col = next(c for c in ent.columns if c.name == 'owner')
        self.assertEqual(col.kwargs.get('on_delete'), 'models.CASCADE')

    def test_one_to_one(self):
        ent = self._entity_for(
            "    #[ORM\\OneToOne(targetEntity: Profile::class)]\n"
            "    private Profile $profile;\n"
        )
        col = next(c for c in ent.columns if c.name == 'profile')
        self.assertEqual(col.django_type, 'OneToOneField')

    def test_many_to_many(self):
        ent = self._entity_for(
            "    #[ORM\\ManyToMany(targetEntity: Tag::class)]\n"
            "    private $tags;\n"
        )
        col = next(c for c in ent.columns if c.name == 'tags')
        self.assertEqual(col.django_type, 'ManyToManyField')


class FileWalkerTests(SimpleTestCase):

    def test_parse_doctrine_directory(self):
        tmp = Path(tempfile.mkdtemp())
        app = tmp / 'symfony'
        (app / 'src' / 'Entity').mkdir(parents=True)
        (app / 'src' / 'Entity' / 'User.php').write_text(dedent("""\
            <?php
            namespace App\\Entity;
            #[ORM\\Entity]
            #[ORM\\Table(name: 'users')]
            class User {
                #[ORM\\Id]
                #[ORM\\GeneratedValue]
                #[ORM\\Column(type: 'integer')]
                private int $id;

                #[ORM\\Column(type: 'string', length: 180, unique: true)]
                private string $email;
            }
        """))
        result = parse_doctrine(app)
        self.assertEqual(len(result.entities), 1)
        ent = result.entities[0]
        self.assertEqual(ent.class_name, 'User')
        self.assertEqual(ent.db_table, 'users')
        names = sorted(c.name for c in ent.columns)
        self.assertEqual(names, ['email', 'id'])


class ModelsRenderingTests(SimpleTestCase):

    def test_render_basic_models(self):
        from datalift.doctrine_lifter import (
            DoctrineColumn, DoctrineEntity, DoctrineLiftResult,
        )
        result = DoctrineLiftResult(entities=[
            DoctrineEntity(
                source=Path('User.php'),
                class_name='User', db_table='users',
                columns=[
                    DoctrineColumn(name='id', db_name='id',
                                    django_type='AutoField',
                                    kwargs={'primary_key': True}),
                    DoctrineColumn(name='email', db_name='email',
                                    django_type='CharField',
                                    kwargs={'max_length': 180,
                                            'unique': True}),
                ],
            ),
        ])
        text = render_models(result)
        self.assertIn('class User(models.Model):', text)
        self.assertIn('models.AutoField(primary_key=True)', text)
        self.assertIn("db_table = 'users'", text)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_models_doctrine(self):
        from datalift.doctrine_lifter import (
            DoctrineColumn, DoctrineEntity, DoctrineLiftResult,
        )
        tmp = Path(tempfile.mkdtemp())
        proj = tmp / 'proj'; proj.mkdir()
        result = DoctrineLiftResult(entities=[
            DoctrineEntity(source=Path('U.php'), class_name='U',
                            db_table='us',
                            columns=[DoctrineColumn(
                                name='x', db_name='x',
                                django_type='CharField',
                                kwargs={'max_length': 10})]),
        ])
        apply(result, proj, 'myapp')
        body = (proj / 'myapp' / 'models_doctrine.py').read_text()
        self.assertIn('class U(models.Model):', body)

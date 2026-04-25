"""Tests for datalift.twig_lifter — the Twig → Django translator."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from datalift.twig_lifter import (
    apply,
    parse_theme,
    render_worklist,
    translate_template,
)


class OutputExpressionTests(SimpleTestCase):

    def test_bare_variable(self):
        out, _ = translate_template('{{ user }}')
        self.assertIn('{{ user }}', out)

    def test_filter_passthrough(self):
        out, _ = translate_template('{{ user.name|upper }}')
        self.assertIn('{{ user.name|upper }}', out)

    def test_filter_with_paren_arg(self):
        out, _ = translate_template("{{ post.date|date('Y-m-d') }}")
        self.assertIn("|date:'Y-m-d'", out)

    def test_filter_with_double_quote_paren_arg(self):
        out, _ = translate_template('{{ post.date|date("Y-m-d") }}')
        self.assertIn('|date:"Y-m-d"', out)

    def test_filter_chain(self):
        out, _ = translate_template('{{ x|upper|escape }}')
        self.assertIn('{{ x|upper|escape }}', out)

    def test_null_coalesce(self):
        out, _ = translate_template("{{ user.name ?? 'guest' }}")
        self.assertIn("|default:'guest'", out)

    def test_ternary_string_literals(self):
        out, _ = translate_template("{{ active ? 'on' : 'off' }}")
        self.assertIn('{% if active %}', out)
        self.assertIn('on', out)
        self.assertIn('off', out)
        self.assertIn('{% endif %}', out)


class ControlFlowTests(SimpleTestCase):

    def test_if_passthrough(self):
        out, _ = translate_template('{% if user %}hi{% endif %}')
        self.assertIn('{% if user %}', out)
        self.assertIn('{% endif %}', out)

    def test_elseif_to_elif(self):
        out, _ = translate_template(
            '{% if x %}a{% elseif y %}b{% else %}c{% endif %}'
        )
        self.assertIn('{% elif y %}', out)
        self.assertIn('{% else %}', out)

    def test_for_passthrough(self):
        out, _ = translate_template('{% for u in users %}{{ u }}{% endfor %}')
        self.assertIn('{% for u in users %}', out)
        self.assertIn('{% endfor %}', out)

    def test_block_passthrough(self):
        out, _ = translate_template('{% block content %}body{% endblock %}')
        self.assertIn('{% block content %}', out)
        self.assertIn('{% endblock %}', out)


class IncludeExtendsTests(SimpleTestCase):

    def test_include_remaps_extension(self):
        out, _ = translate_template("{% include 'partials/header.html.twig' %}")
        self.assertIn("{% include 'partials/header.html' %}", out)

    def test_extends_remaps_extension(self):
        out, _ = translate_template("{% extends 'base.html.twig' %}")
        self.assertIn("{% extends 'base.html' %}", out)

    def test_bare_twig_extension(self):
        out, _ = translate_template("{% include 'sidebar.twig' %}")
        self.assertIn("{% include 'sidebar.html' %}", out)


class TwigSpecificTests(SimpleTestCase):

    def test_set_emits_porter_marker(self):
        out, skipped = translate_template("{% set name = 'test' %}body")
        self.assertIn('twig set', out)
        self.assertIn('body', out)
        self.assertEqual(skipped, [])

    def test_macro_emits_porter_marker(self):
        out, _ = translate_template(
            "{% macro input(name, value) %}<input>{% endmacro %}"
        )
        self.assertIn('twig macro', out)

    def test_embed_translates_with_porter_note(self):
        out, _ = translate_template(
            "{% embed 'card.html.twig' %}body{% endembed %}"
        )
        self.assertIn("{% include 'card.html' %}", out)
        self.assertIn('twig embed', out)

    def test_inline_block_form(self):
        """Twig allows ``{% block title page_title|trans %}``. We open
        the block, comment the inline body."""
        out, skipped = translate_template(
            "{% block title page_title|upper %}"
        )
        self.assertIn('{% block title %}', out)
        self.assertIn('inline block body', out)
        # Recorded as a skipped fragment for the porter.
        self.assertEqual(len(skipped), 1)


class CommentTests(SimpleTestCase):

    def test_comment_preserved(self):
        """Twig and Django both use {# ... #} — passthrough."""
        out, _ = translate_template('{# a comment #}<p>real</p>')
        self.assertIn('{# a comment #}', out)
        self.assertIn('<p>real</p>', out)

    def test_multiline_comment_preserved(self):
        out, _ = translate_template('before\n{# multi\n  line #}\nafter')
        self.assertIn('multi', out)


class WalkerTests(SimpleTestCase):

    def test_parse_theme_picks_up_twig_files(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'index.html.twig').write_text('{{ user }}')
        (theme / 'mail.txt.twig').write_text('Hi {{ user }}')
        (theme / 'config.php').write_text('<?php // ?>')
        (theme / 'style.css').write_text('body{}')
        result = parse_theme(theme)
        names = sorted(r.target_name for r in result.records)
        self.assertEqual(names, ['index.html', 'mail.txt'])
        self.assertEqual([p.name for p in result.unhandled_files], ['config.php'])
        self.assertEqual([p.name for p in result.static_assets], ['style.css'])

    def test_apply_writes_translated_file(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'page.html.twig').write_text(
            "{% extends 'base.html.twig' %}{% block content %}{{ post.title }}{% endblock %}"
        )
        proj = tmp / 'proj'
        proj.mkdir()
        result = parse_theme(theme)
        apply(result, proj, 'cms')
        body = (proj / 'templates' / 'cms' / 'page.html').read_text()
        self.assertIn("{% extends 'base.html' %}", body)
        self.assertIn('{% block content %}', body)
        self.assertIn('{{ post.title }}', body)


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_translated_and_unhandled(self):
        from datalift.twig_lifter import LiftResult, TemplateRecord
        result = LiftResult(
            records=[
                TemplateRecord(
                    source=Path('page.html.twig'),
                    target_name='page.html',
                    body='',
                    skipped=['flush'],
                ),
            ],
            unhandled_files=[Path('functions.php')],
            static_assets=[Path('style.css')],
        )
        text = render_worklist(result, 'cms', Path('/tmp/theme'))
        self.assertIn('liftwig worklist', text)
        self.assertIn('page.html.twig', text)
        self.assertIn('1 unhandled fragments', text)
        self.assertIn('functions.php', text)
        self.assertIn('flush', text)


class RealisticSampleTests(SimpleTestCase):
    """A realistic Symfony / Drupal-shaped Twig template should
    translate cleanly enough to compile under Django's loader."""

    SAMPLE = """{% extends 'base.html.twig' %}

{% block title %}Posts{% endblock %}

{% block content %}
<ul class="posts">
{% for post in posts %}
  <li>
    <a href="{{ path('post_detail', {id: post.id}) }}">{{ post.title }}</a>
    <small>{{ post.publishedAt|date('M j, Y') }}</small>
    {% if post.author %}
      &mdash; {{ post.author.name|default('Anonymous') }}
    {% endif %}
  </li>
{% else %}
  <li>No posts yet.</li>
{% endfor %}
</ul>
{% endblock %}"""

    def test_full_translation(self):
        out, _skipped = translate_template(self.SAMPLE)
        self.assertIn("{% extends 'base.html' %}", out)
        self.assertIn('{% block content %}', out)
        self.assertIn('{% for post in posts %}', out)
        self.assertIn("|date:'M j, Y'", out)
        self.assertIn('{% if post.author %}', out)
        self.assertIn("|default:'Anonymous'", out)
        # No unhandled fragments — `path()` is left as a Twig function call
        # that the porter will see when Django can't resolve it.
        self.assertIn('{% endfor %}', out)
        self.assertIn('{% endblock %}', out)

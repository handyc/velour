"""Tests for datalift.volt_lifter — Phalcon Volt → Django.

Volt is Twig-shaped, so most behaviour is inherited from
test_twig_lifter via the underlying twig_lifter; these tests focus
on the Volt-specific surface (`.volt` extension remap, file walker)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from datalift.volt_lifter import (
    apply, parse_theme, render_worklist, translate_template,
)


class VoltExtensionTests(SimpleTestCase):

    def test_include_volt_extension_remapped(self):
        out, _ = translate_template("{% include 'partials/header.volt' %}")
        self.assertIn("{% include 'partials/header.html' %}", out)

    def test_extends_volt_extension_remapped(self):
        out, _ = translate_template("{% extends 'base.volt' %}")
        self.assertIn("{% extends 'base.html' %}", out)


class TwigPassthroughTests(SimpleTestCase):
    """Volt inherits Twig syntax — these confirm the delegation works."""

    def test_simple_var(self):
        out, _ = translate_template('{{ user.name }}')
        self.assertIn('{{ user.name }}', out)

    def test_if_else_endif(self):
        out, _ = translate_template('{% if x %}A{% else %}B{% endif %}')
        self.assertIn('{% if x %}', out)
        self.assertIn('{% else %}', out)

    def test_for_in(self):
        out, _ = translate_template('{% for x in xs %}{{ x }}{% endfor %}')
        self.assertIn('{% for x in xs %}', out)
        self.assertIn('{% endfor %}', out)

    def test_filter_paren_arg_translated(self):
        out, _ = translate_template("{{ d|date('Y-m-d') }}")
        self.assertIn("|date:'Y-m-d'", out)


class WalkerTests(SimpleTestCase):

    def test_parse_theme_picks_up_volt(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'views'
        theme.mkdir()
        (theme / 'index.volt').write_text("{% extends 'base.volt' %}")
        (theme / 'controller.php').write_text("<?php // ?>")
        (theme / 'app.css').write_text("body{}")
        result = parse_theme(theme)
        names = sorted(r.target_name for r in result.records)
        self.assertEqual(names, ['index.html'])
        self.assertEqual([p.name for p in result.unhandled_files],
                         ['controller.php'])

    def test_apply_writes_translated(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'views'
        theme.mkdir()
        (theme / 'page.volt').write_text(
            "{% extends 'layouts/main.volt' %}"
            "{% block content %}{{ post.title }}{% endblock %}"
        )
        proj = tmp / 'proj'
        proj.mkdir()
        result = parse_theme(theme)
        apply(result, proj, 'phalcon')
        body = (proj / 'templates' / 'phalcon' / 'page.html').read_text()
        self.assertIn("{% extends 'layouts/main.html' %}", body)
        self.assertIn('{{ post.title }}', body)


class WorklistTests(SimpleTestCase):

    def test_worklist_format(self):
        from datalift.volt_lifter import LiftResult, TemplateRecord
        result = LiftResult(records=[
            TemplateRecord(source=Path('a.volt'), target_name='a.html', body=''),
        ])
        text = render_worklist(result, 'app', Path('/tmp/theme'))
        self.assertIn('liftvolt worklist', text)
        self.assertIn('a.volt', text)

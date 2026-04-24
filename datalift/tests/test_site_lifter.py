"""Tests for datalift.site_lifter.

`site_lifter` routes legacy site files into Django's
`templates/`+`static/` layout and rewrites `<script src="js/app.js">`
to `<script src="{% static 'app/js/app.js' %}">`. Used by the
`liftsite` management command.

Run via:
    venv/bin/python manage.py test datalift.tests.test_site_lifter
"""

from pathlib import Path

from django.test import SimpleTestCase

from datalift.site_lifter import (
    classify,
    has_django_markers,
    rewrite_html,
    scan_js_endpoints,
    target_relpath,
)


class ClassifyTests(SimpleTestCase):
    def test_html(self):
        self.assertEqual(classify(Path('index.html')), 'html')
        self.assertEqual(classify(Path('admin/dashboard.htm')), 'html')

    def test_js(self):
        self.assertEqual(classify(Path('app.js')), 'js')
        self.assertEqual(classify(Path('src/main.mjs')), 'js')

    def test_css(self):
        self.assertEqual(classify(Path('style.css')), 'css')

    def test_asset_images(self):
        self.assertEqual(classify(Path('logo.png')), 'asset')
        self.assertEqual(classify(Path('photo.jpg')), 'asset')
        self.assertEqual(classify(Path('icon.svg')), 'asset')

    def test_asset_fonts(self):
        self.assertEqual(classify(Path('font.woff2')), 'asset')

    def test_asset_media(self):
        self.assertEqual(classify(Path('intro.mp4')), 'asset')

    def test_php(self):
        self.assertEqual(classify(Path('index.php')), 'php')
        self.assertEqual(classify(Path('header.phtml')), 'php')

    def test_unknown_goes_to_other(self):
        self.assertEqual(classify(Path('README')), 'other')
        self.assertEqual(classify(Path('whatever.xyz')), 'other')


class TargetRelpathTests(SimpleTestCase):
    def test_html_goes_to_templates(self):
        self.assertEqual(
            target_relpath('html', 'myapp', Path('index.html')),
            Path('templates/myapp/index.html'),
        )

    def test_js_goes_to_static_js(self):
        self.assertEqual(
            target_relpath('js', 'myapp', Path('app.js')),
            Path('static/myapp/js/app.js'),
        )

    def test_js_strips_duplicate_prefix(self):
        # Source tree has `js/app.js` — target should be
        # `static/myapp/js/app.js` not `static/myapp/js/js/app.js`.
        self.assertEqual(
            target_relpath('js', 'myapp', Path('js/app.js')),
            Path('static/myapp/js/app.js'),
        )

    def test_scripts_alias_strip(self):
        self.assertEqual(
            target_relpath('js', 'myapp', Path('scripts/app.js')),
            Path('static/myapp/js/app.js'),
        )

    def test_css_strips_styles_alias(self):
        self.assertEqual(
            target_relpath('css', 'myapp', Path('styles/theme.css')),
            Path('static/myapp/css/theme.css'),
        )

    def test_asset_strips_images_alias(self):
        self.assertEqual(
            target_relpath('asset', 'myapp', Path('images/logo.png')),
            Path('static/myapp/assets/logo.png'),
        )

    def test_php_returns_none(self):
        # Datalift deliberately doesn't route PHP — that's
        # liftphp's job, not liftsite's.
        self.assertIsNone(target_relpath('php', 'myapp', Path('index.php')))

    def test_other_returns_none(self):
        self.assertIsNone(target_relpath('other', 'myapp', Path('README')))


class HasDjangoMarkersTests(SimpleTestCase):
    """Files that already carry Django/Jinja tags shouldn't be
    silently rewritten — operator's hand-work gets respected."""

    def test_plain_html_is_clean(self):
        self.assertFalse(has_django_markers('<p>hello</p>'))

    def test_detects_block_tag(self):
        self.assertTrue(has_django_markers('{% block content %}'))

    def test_detects_variable_tag(self):
        self.assertTrue(has_django_markers('{{ user.name }}'))

    def test_detects_comment_tag(self):
        self.assertTrue(has_django_markers('{# just a note #}'))


class RewriteHtmlTests(SimpleTestCase):
    """The `<script src="…">` rewriter: relative asset paths become
    `{% static 'app/js/…' %}`, external / scheme-based URLs are
    left alone."""

    def test_rewrites_relative_script_src(self):
        html = '<script src="js/app.js"></script>'
        out = rewrite_html(html, 'myapp').text
        self.assertIn("{% static 'myapp/js/app.js' %}", out)

    def test_rewrites_css_link(self):
        html = '<link rel="stylesheet" href="css/style.css">'
        out = rewrite_html(html, 'myapp').text
        self.assertIn("{% static 'myapp/css/style.css' %}", out)

    def test_rewrites_image_src(self):
        html = '<img src="images/logo.png">'
        out = rewrite_html(html, 'myapp').text
        self.assertIn("{% static 'myapp/assets/logo.png' %}", out)

    def test_absolute_url_left_alone(self):
        html = '<script src="https://cdn.example.com/jquery.js"></script>'
        out = rewrite_html(html, 'myapp').text
        self.assertIn('cdn.example.com/jquery.js', out)
        self.assertNotIn('{% static', out)

    def test_protocol_relative_url_left_alone(self):
        html = '<script src="//cdn.example.com/lib.js"></script>'
        out = rewrite_html(html, 'myapp').text
        self.assertNotIn('{% static', out)

    def test_anchor_href_left_alone(self):
        html = '<a href="#section-1">Jump</a>'
        out = rewrite_html(html, 'myapp').text
        self.assertIn('#section-1', out)
        self.assertNotIn('{% static', out)

    def test_already_djangoified_left_alone(self):
        # Files with existing template tags shouldn't be double-
        # rewritten.
        html = "<script src=\"{% static 'myapp/js/app.js' %}\"></script>"
        out = rewrite_html(html, 'myapp').text
        self.assertEqual(html, out)

    def test_mailto_left_alone(self):
        html = '<a href="mailto:admin@example.com">contact</a>'
        out = rewrite_html(html, 'myapp').text
        self.assertIn('mailto:admin@example.com', out)

    def test_load_static_tag_is_prepended(self):
        # When any rewrite happens, `{% load static %}` is added
        # to the top so Django actually resolves the tag.
        html = '<script src="js/app.js"></script>'
        out = rewrite_html(html, 'myapp').text
        self.assertIn('{% load static %}', out)


class ScanJsEndpointsTests(SimpleTestCase):
    """`scan_js_endpoints` finds URLs baked into JavaScript that
    the operator will probably want to reconnect to Django views."""

    def test_finds_fetch_url(self):
        js = "fetch('/api/users/42/');"
        self.assertIn('/api/users/42/', scan_js_endpoints(js))

    def test_finds_axios_url(self):
        js = "axios.post('/admin/delete/123', {});"
        self.assertIn('/admin/delete/123', scan_js_endpoints(js))

    def test_finds_jquery_ajax_url(self):
        js = "$.get('/api/users', cb);"
        self.assertIn('/api/users', scan_js_endpoints(js))

    def test_ignores_relative_fragment(self):
        # A string like `'#tab'` isn't an endpoint.
        js = "document.querySelector('#tab-1')"
        eps = scan_js_endpoints(js)
        self.assertNotIn('#tab-1', eps)

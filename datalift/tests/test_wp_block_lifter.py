"""Tests for datalift.wp_block_lifter — WP block themes → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.wp_block_lifter import (
    apply, lift_block_template, parse_block_theme, render_worklist,
    _BlockLifter,
)


class StaticBlockTests(SimpleTestCase):

    def test_paragraph_block_strips_to_inner(self):
        out, _, _ = lift_block_template(
            '<!-- wp:paragraph --><p>Hello</p><!-- /wp:paragraph -->'
        )
        self.assertIn('<p>Hello</p>', out)
        self.assertNotIn('wp:paragraph', out)

    def test_group_block_passes_through(self):
        out, _, _ = lift_block_template(
            '<!-- wp:group --><div>x</div><!-- /wp:group -->'
        )
        self.assertIn('<div>x</div>', out)
        self.assertNotIn('wp:group', out)

    def test_separator(self):
        out, _, _ = lift_block_template(
            '<!-- wp:separator --><hr/><!-- /wp:separator -->'
        )
        self.assertIn('<hr', out)

    def test_spacer(self):
        out, _, _ = lift_block_template(
            '<!-- wp:spacer {"height":48} /-->'
        )
        self.assertIn('height:48px', out)
        self.assertIn('wp-block-spacer', out)


class DynamicBlockTests(SimpleTestCase):

    def test_template_part(self):
        out, _, _ = lift_block_template(
            '<!-- wp:template-part {"slug":"header","tagName":"header"} /-->'
        )
        self.assertIn('{% include "parts/header.html" %}', out)
        self.assertIn('<header>', out)

    def test_template_part_default_tag(self):
        out, _, _ = lift_block_template(
            '<!-- wp:template-part {"slug":"footer"} /-->'
        )
        self.assertIn('{% include "parts/footer.html" %}', out)

    def test_post_title_simple(self):
        out, _, _ = lift_block_template('<!-- wp:post-title /-->')
        self.assertIn('post.title', out)
        self.assertIn('<h2', out)

    def test_post_title_link(self):
        out, _, _ = lift_block_template(
            '<!-- wp:post-title {"isLink":true,"level":1} /-->'
        )
        self.assertIn('<h1', out)
        self.assertIn('post.get_absolute_url', out)

    def test_post_content(self):
        out, _, _ = lift_block_template('<!-- wp:post-content /-->')
        self.assertIn('post.content|safe', out)

    def test_post_excerpt(self):
        out, _, _ = lift_block_template('<!-- wp:post-excerpt /-->')
        self.assertIn('post.excerpt', out)

    def test_post_date_format_translated(self):
        out, _, _ = lift_block_template(
            '<!-- wp:post-date {"format":"F j, Y"} /-->'
        )
        self.assertIn('post.published_at|date:"F j, Y"', out)

    def test_post_featured_image(self):
        out, _, _ = lift_block_template(
            '<!-- wp:post-featured-image {"isLink":true} /-->'
        )
        self.assertIn('post.featured_image.url', out)
        self.assertIn('post.get_absolute_url', out)

    def test_site_logo(self):
        out, _, _ = lift_block_template('<!-- wp:site-logo {"width":64} /-->')
        self.assertIn('width:64px', out)
        self.assertIn('site.logo', out)

    def test_site_title(self):
        out, _, _ = lift_block_template('<!-- wp:site-title /-->')
        self.assertIn('site.name', out)

    def test_post_author(self):
        out, _, _ = lift_block_template('<!-- wp:post-author /-->')
        self.assertIn('post.author', out)


class QueryLoopTests(SimpleTestCase):

    def test_query_with_post_template(self):
        php = dedent('''\
            <!-- wp:query {"query":{"perPage":10,"postType":"post"}} -->
            <main><!-- wp:post-template -->
            <!-- wp:post-title /-->
            <!-- wp:post-content /-->
            <!-- /wp:post-template --></main>
            <!-- /wp:query -->
        ''')
        out, _, _ = lift_block_template(php)
        self.assertIn('{% for post in posts %}', out)
        self.assertIn('{% endfor %}', out)
        self.assertIn('post.title', out)
        self.assertIn('post.content|safe', out)
        # Wrapper data attributes preserved
        self.assertIn('data-per-page="10"', out)
        self.assertIn('data-post-type="post"', out)

    def test_query_pagination(self):
        php = ('<!-- wp:query-pagination -->'
               '<!-- wp:query-pagination-previous /-->'
               '<!-- wp:query-pagination-numbers /-->'
               '<!-- wp:query-pagination-next /-->'
               '<!-- /wp:query-pagination -->')
        out, _, _ = lift_block_template(php)
        self.assertIn('posts.has_previous', out)
        self.assertIn('posts.has_next', out)
        self.assertIn('posts.paginator.num_pages', out)


class NestedBlockTests(SimpleTestCase):

    def test_nested_groups(self):
        php = dedent('''\
            <!-- wp:group --><div class="outer">
            <!-- wp:group --><div class="inner">x</div><!-- /wp:group -->
            </div><!-- /wp:group -->
        ''')
        out, _, _ = lift_block_template(php)
        self.assertIn('class="outer"', out)
        self.assertIn('class="inner"', out)
        self.assertNotIn('wp:group', out)

    def test_blocks_seen_recorded(self):
        php = ('<!-- wp:group --><div>'
               '<!-- wp:paragraph --><p>x</p><!-- /wp:paragraph -->'
               '</div><!-- /wp:group -->')
        _, blocks, _ = lift_block_template(php)
        self.assertIn('group', blocks)
        self.assertIn('paragraph', blocks)


class WalkerTests(SimpleTestCase):

    def test_parse_minimal_theme(self):
        tmp = Path(tempfile.mkdtemp()) / 'mini'
        (tmp / 'templates').mkdir(parents=True)
        (tmp / 'parts').mkdir(parents=True)
        (tmp / 'theme.json').write_text(
            '{"version":2,"settings":{"color":{}}}'
        )
        (tmp / 'templates' / 'index.html').write_text(
            '<!-- wp:template-part {"slug":"header"} /-->'
            '<!-- wp:post-title /-->'
        )
        (tmp / 'parts' / 'header.html').write_text(
            '<!-- wp:site-title /-->'
        )
        result = parse_block_theme(tmp)
        self.assertEqual(len(result.templates), 1)
        self.assertEqual(len(result.parts), 1)
        self.assertEqual(result.templates[0].name, 'index')
        self.assertEqual(result.parts[0].name, 'header')
        self.assertIsNotNone(result.theme_json)
        self.assertEqual(result.theme_json['version'], 2)


class ApplyTests(SimpleTestCase):

    def test_apply_writes_templates(self):
        from datalift.wp_block_lifter import WpBlockTheme, WpBlockTemplate
        tmp = Path(tempfile.mkdtemp())
        proj = tmp / 'proj'; proj.mkdir()
        result = WpBlockTheme(
            theme_dir=Path('mini'),
            theme_json={'version': 2},
            templates=[WpBlockTemplate(
                source=Path('templates/index.html'),
                name='index', kind='template',
                django_html='<h1>hi</h1>',
            )],
            parts=[WpBlockTemplate(
                source=Path('parts/header.html'),
                name='header', kind='part',
                django_html='<header>x</header>',
            )],
        )
        apply(result, proj, 'myapp')
        idx = (proj / 'templates' / 'myapp' / 'index.html').read_text()
        hdr = (proj / 'templates' / 'myapp' / 'parts' / 'header.html').read_text()
        themejson = (proj / 'myapp' / 'wp_theme.json').read_text()
        self.assertIn('<h1>hi</h1>', idx)
        self.assertIn('<header>x</header>', hdr)
        self.assertIn('"version": 2', themejson)


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_templates_and_blocks(self):
        from datalift.wp_block_lifter import WpBlockTheme, WpBlockTemplate
        result = WpBlockTheme(
            theme_dir=Path('mini'),
            templates=[WpBlockTemplate(
                source=Path('templates/index.html'),
                name='index', kind='template',
                django_html='', blocks_seen=['template-part', 'query'],
            )],
        )
        wl = render_worklist(result, 'myapp')
        self.assertIn('## Templates (1)', wl)
        self.assertIn('templates/index.html', wl)
        self.assertIn('wp:template-part', wl)
        self.assertIn('wp:query', wl)

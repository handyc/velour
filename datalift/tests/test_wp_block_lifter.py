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

    def test_query_title_archive(self):
        out, _, _ = lift_block_template(
            '<!-- wp:query-title {"type":"archive"} /-->')
        self.assertIn('archive_title', out)
        self.assertIn('data-type="archive"', out)

    def test_query_title_search_default(self):
        out, _, _ = lift_block_template('<!-- wp:query-title /-->')
        self.assertIn('archive_title', out)

    def test_term_description(self):
        out, _, _ = lift_block_template('<!-- wp:term-description /-->')
        self.assertIn('term_description', out)
        self.assertIn('|safe', out)

    def test_search_block(self):
        out, _, _ = lift_block_template(
            '<!-- wp:search {"label":"Find","buttonText":"Go"} /-->')
        self.assertIn('action="/search/"', out)
        self.assertIn('name="s"', out)
        self.assertIn('search_query', out)
        self.assertIn('Go', out)

    def test_pattern_block(self):
        out, _, p = lift_block_template(
            '<!-- wp:pattern {"slug":"twentytwentytwo/hidden-404"} /-->')
        self.assertIn('twentytwentytwo/hidden-404', out)
        self.assertIn('pattern_twentytwentytwo_hidden_404', out)
        self.assertEqual(p, 1)  # one porter marker

    def test_post_navigation_previous(self):
        out, _, _ = lift_block_template(
            '<!-- wp:post-navigation-link {"type":"previous"} /-->')
        self.assertIn('prev_post', out)
        self.assertIn('← Previous', out)

    def test_post_navigation_next(self):
        out, _, _ = lift_block_template(
            '<!-- wp:post-navigation-link {"type":"next"} /-->')
        self.assertIn('next_post', out)
        self.assertIn('Next →', out)

    def test_post_comments_default_loop(self):
        out, _, _ = lift_block_template('<!-- wp:post-comments /-->')
        self.assertIn('{% for c in comments %}', out)
        self.assertIn('c.comment_author', out)
        self.assertIn('c.comment_date', out)
        self.assertIn('c.comment_content', out)


class DynamicWidgetBlockTests(SimpleTestCase):
    """Dynamic blocks that need a Django context variable to work —
    latest-posts, latest-comments, archives, tag-cloud, calendar,
    embeds, etc."""

    def test_embed_youtube_with_url(self):
        out, _, _ = lift_block_template(
            '<!-- wp:embed {"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"'
            ',"providerNameSlug":"youtube"} /-->')
        self.assertIn('youtube.com/embed/dQw4w9WgXcQ', out)
        self.assertIn('<iframe', out)

    def test_embed_legacy_core_embed(self):
        out, _, _ = lift_block_template(
            '<!-- wp:core-embed/youtube -->'
            '<figure><div>https://youtu.be/dQw4w9WgXcQ</div></figure>'
            '<!-- /wp:core-embed/youtube -->')
        self.assertIn('youtube.com/embed/dQw4w9WgXcQ', out)

    def test_embed_vimeo(self):
        out, _, _ = lift_block_template(
            '<!-- wp:embed {"url":"https://vimeo.com/123456",'
            '"providerNameSlug":"vimeo"} /-->')
        self.assertIn('player.vimeo.com/video/123456', out)

    def test_embed_unknown_provider_falls_back_to_link(self):
        out, _, _ = lift_block_template(
            '<!-- wp:embed {"url":"https://example.com/foo"} /-->')
        self.assertIn('href="https://example.com/foo"', out)

    def test_latest_posts(self):
        out, _, _ = lift_block_template(
            '<!-- wp:latest-posts {"postsToShow":3} /-->')
        self.assertIn('latest_posts', out)
        self.assertIn('slice:":3"', out)

    def test_latest_comments(self):
        out, _, _ = lift_block_template('<!-- wp:latest-comments /-->')
        self.assertIn('latest_comments', out)
        self.assertIn('comment_author', out)

    def test_archives(self):
        out, _, _ = lift_block_template('<!-- wp:archives /-->')
        self.assertIn('archive_months', out)
        self.assertIn('m.month_name', out)

    def test_tag_cloud(self):
        out, _, _ = lift_block_template('<!-- wp:tag-cloud /-->')
        self.assertIn('tag_cloud', out)
        self.assertIn('/tag/', out)

    def test_calendar(self):
        out, _, _ = lift_block_template('<!-- wp:calendar /-->')
        self.assertIn('calendar_html', out)

    def test_avatar(self):
        out, _, _ = lift_block_template(
            '<!-- wp:avatar {"size":64} /-->')
        self.assertIn('avatar_url', out)
        self.assertIn('width="64"', out)

    def test_loginout(self):
        out, _, _ = lift_block_template('<!-- wp:loginout /-->')
        self.assertIn('is_authenticated', out)
        self.assertIn('Log in', out)

    def test_read_more(self):
        out, _, _ = lift_block_template(
            '<!-- wp:read-more {"content":"Continue reading"} /-->')
        self.assertIn('Continue reading', out)
        self.assertIn('post.get_absolute_url', out)

    def test_query_no_results(self):
        out, _, _ = lift_block_template(
            '<!-- wp:query-no-results --><p>None.</p><!-- /wp:query-no-results -->')
        self.assertIn('{% if not posts', out)
        self.assertIn('None.', out)

    def test_comments_title(self):
        out, _, _ = lift_block_template('<!-- wp:comments-title /-->')
        self.assertIn('comments|length', out)

    def test_comment_template(self):
        out, _, _ = lift_block_template(
            '<!-- wp:comment-template -->'
            '<p>x</p>'
            '<!-- /wp:comment-template -->')
        self.assertIn('{% for c in comments %}', out)
        self.assertIn('<p>x</p>', out)

    def test_comment_author_name(self):
        out, _, _ = lift_block_template('<!-- wp:comment-author-name /-->')
        self.assertIn('c.comment_author', out)

    def test_comment_reply_link(self):
        out, _, _ = lift_block_template('<!-- wp:comment-reply-link /-->')
        self.assertIn('reply-{{ c.comment_id }}', out)


class StaticBlockLongTailTests(SimpleTestCase):
    """The TUT corpus exercises gallery / cover / code / pullquote /
    audio / video / file / list / table / columns / group / button /
    media-text / social-links / quote / verse / preformatted, all of
    which WP stores as already-rendered HTML inside the block
    comment. The lifter just needs to drop the comment markers,
    preserve inner HTML, and not bump the porter count."""

    BLOCKS = [
        'gallery', 'cover', 'code', 'preformatted', 'verse',
        'pullquote', 'quote', 'audio', 'video', 'file', 'media-text',
        'columns', 'column', 'group', 'buttons', 'button', 'table',
        'list', 'list-item', 'social-links', 'social-link', 'details',
        'footnotes',
    ]

    def test_each_static_block_passes_inner_html_unchanged(self):
        for name in self.BLOCKS:
            with self.subTest(block=name):
                src = (f'<!-- wp:{name} {{"id":42}} -->'
                       f'<div class="wp-block-{name}">PAYLOAD</div>'
                       f'<!-- /wp:{name} -->')
                out, blocks, porters = lift_block_template(src)
                self.assertIn('PAYLOAD', out)
                self.assertNotIn('<!-- wp:', out)
                self.assertNotIn('<!-- /wp:', out)
                self.assertEqual(porters, 0,
                    f'wp:{name} should not bump porter count')
                self.assertIn(name, blocks)

    def test_image_block_does_not_double_wrap(self):
        # Regression: _t_image used to wrap inner_html in another
        # <figure class="wp-block-image">, producing nested figures.
        src = (
            '<!-- wp:image {"id":616} -->'
            '<figure class="wp-block-image size-full">'
            '<img src="x.jpg" class="wp-image-616"/></figure>'
            '<!-- /wp:image -->'
        )
        out, _, _ = lift_block_template(src)
        # Exactly one opening <figure ...> in output.
        self.assertEqual(out.count('<figure'), 1)

    def test_more_block_emits_marker_not_porter(self):
        out, _, porters = lift_block_template('<!-- wp:more /-->')
        self.assertEqual(porters, 0)
        self.assertIn('wp-block-more', out)
        self.assertNotIn('<!-- wp:', out)

    def test_nextpage_block_emits_marker_not_porter(self):
        out, _, porters = lift_block_template('<!-- wp:nextpage /-->')
        self.assertEqual(porters, 0)
        self.assertIn('wp-block-nextpage', out)


class ClassicShortcodeTests(SimpleTestCase):
    """The TUT post-format corpus uses classic shortcodes
    [caption ...] and [gallery ...] in raw post bodies (not wrapped
    in wp:shortcode comments). The lifter expands them to
    real HTML so they don't leak as text to the browser."""

    def test_caption_attr_form(self):
        # Older form: caption text supplied as an attribute.
        src = ('[caption id="attachment_612" align="aligncenter" '
               'width="640" caption="Burns like a spinifex log."]'
               '<a href="x.jpg"><img src="x.jpg" /></a>'
               '[/caption]')
        out, _, _ = lift_block_template(src)
        self.assertIn('<figure class="wp-block-image aligncenter"', out)
        self.assertIn('style="width:640px"', out)
        self.assertIn('Burns like a spinifex log.', out)
        self.assertIn('<figcaption', out)
        self.assertNotIn('[caption', out)

    def test_caption_inline_form(self):
        # Newer form: caption text supplied after the <img>.
        src = ('[caption id="x" align="alignnone" width="300"]'
               '<img src="x.jpg" /> Caption sits after the image.'
               '[/caption]')
        out, _, _ = lift_block_template(src)
        self.assertIn('Caption sits after the image.', out)
        self.assertIn('<figcaption', out)

    def test_gallery_with_ids(self):
        out, _, _ = lift_block_template('[gallery ids="1,2,3" columns="2"]')
        self.assertIn('wp-block-gallery', out)
        self.assertIn('columns-2', out)
        self.assertIn('attachment-1', out)
        self.assertIn('attachment-3', out)
        self.assertNotIn('[gallery', out)

    def test_gallery_bare(self):
        out, _, _ = lift_block_template('[gallery]')
        self.assertIn('wp-block-gallery', out)
        self.assertNotIn('[gallery', out)

    def test_shortcode_expansion_idempotent_on_clean_html(self):
        src = '<p>Plain old paragraph.</p>'
        out, _, _ = lift_block_template(src)
        self.assertEqual(out, src)


class PatternResolutionTests(SimpleTestCase):
    """Real-world block themes (Twenty Twenty-Four, …) compose
    their templates almost entirely out of wp:pattern references
    that point into the theme's patterns/*.php files. Without
    pattern resolution, the lifted index.html is empty and the
    demo home page renders as just the header. With it, the
    pattern's markup is spliced inline and recursively lifted."""

    def test_pattern_with_no_map_falls_back_to_porter_slot(self):
        out, _, porters = lift_block_template(
            '<!-- wp:pattern {"slug":"foo/bar"} /-->')
        self.assertIn('PORTER', out)
        self.assertIn('pattern_foo_bar', out)
        self.assertGreaterEqual(porters, 1)

    def test_pattern_with_map_splices_markup_inline(self):
        patterns = {
            'mytheme/hello': (
                '<!-- wp:paragraph -->'
                '<p>Hello from a resolved pattern.</p>'
                '<!-- /wp:paragraph -->'),
        }
        out, _, porters = lift_block_template(
            '<!-- wp:pattern {"slug":"mytheme/hello"} /-->',
            patterns=patterns)
        self.assertIn('Hello from a resolved pattern.', out)
        self.assertNotIn('PORTER', out)
        self.assertNotIn('<!-- wp:', out)
        # The recursively-lifted pattern should not bump the
        # porter count just by being resolved.
        self.assertEqual(porters, 0)

    def test_pattern_resolution_is_recursive(self):
        # Pattern A references pattern B; B contains real markup.
        patterns = {
            'mytheme/a': '<!-- wp:pattern {"slug":"mytheme/b"} /-->',
            'mytheme/b': '<!-- wp:heading --><h2>B</h2><!-- /wp:heading -->',
        }
        out, _, _ = lift_block_template(
            '<!-- wp:pattern {"slug":"mytheme/a"} /-->',
            patterns=patterns)
        self.assertIn('<h2>B</h2>', out)
        self.assertNotIn('<!-- wp:', out)

    def test_pattern_resolution_breaks_cycles(self):
        # A → B → A — should not infinite-loop.
        patterns = {
            'mytheme/a': '<!-- wp:pattern {"slug":"mytheme/b"} /-->',
            'mytheme/b': '<!-- wp:pattern {"slug":"mytheme/a"} /-->',
        }
        out, _, porters = lift_block_template(
            '<!-- wp:pattern {"slug":"mytheme/a"} /-->',
            patterns=patterns)
        self.assertIn('pattern cycle', out)
        self.assertGreaterEqual(porters, 1)


class PatternWalkerTests(SimpleTestCase):
    """parse_theme_patterns walks <theme>/patterns/*.php and
    returns a slug → block-markup map."""

    def test_parse_theme_patterns_extracts_slug_and_body(self):
        import tempfile
        from pathlib import Path
        from datalift.wp_block_lifter import parse_theme_patterns
        with tempfile.TemporaryDirectory() as td:
            theme = Path(td)
            (theme / 'patterns').mkdir()
            (theme / 'patterns' / 'p1.php').write_text(
                '<?php\n'
                '/**\n'
                ' * Title: My pattern\n'
                ' * Slug: mytheme/p1\n'
                ' * Categories: query\n'
                ' */\n'
                '?>\n'
                '<!-- wp:paragraph --><p>Body.</p><!-- /wp:paragraph -->\n')
            patterns = parse_theme_patterns(theme)
            self.assertIn('mytheme/p1', patterns)
            self.assertIn('<p>Body.</p>', patterns['mytheme/p1'])

    def test_parse_theme_patterns_skips_files_without_slug_header(self):
        import tempfile
        from pathlib import Path
        from datalift.wp_block_lifter import parse_theme_patterns
        with tempfile.TemporaryDirectory() as td:
            theme = Path(td)
            (theme / 'patterns').mkdir()
            (theme / 'patterns' / 'noslug.php').write_text(
                '<?php /** Title: noslug */ ?>\n<p>x</p>')
            self.assertEqual(parse_theme_patterns(theme), {})

    def test_parse_theme_patterns_returns_empty_when_no_dir(self):
        import tempfile
        from pathlib import Path
        from datalift.wp_block_lifter import parse_theme_patterns
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(parse_theme_patterns(Path(td)), {})


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

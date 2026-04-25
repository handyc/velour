"""Tests for datalift.wp_lifter — the WordPress theme → Django translator."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from datalift.wp_lifter import (
    apply,
    generate_urls,
    generate_views,
    parse_theme,
    render_worklist,
    translate_template,
)


class TranslateTemplateTests(SimpleTestCase):
    """Statement-by-statement translation of the standard WP tags."""

    def test_get_header_becomes_include(self):
        out, skipped = translate_template('<?php get_header(); ?>')
        self.assertIn("{% include 'wp/header.html' %}", out)
        self.assertEqual(skipped, [])

    def test_get_footer_becomes_include(self):
        out, _ = translate_template('<?php get_footer(); ?>')
        self.assertIn("{% include 'wp/footer.html' %}", out)

    def test_get_sidebar_becomes_include(self):
        out, _ = translate_template('<?php get_sidebar(); ?>')
        self.assertIn("{% include 'wp/sidebar.html' %}", out)

    def test_have_posts_becomes_django_if(self):
        out, _ = translate_template('<?php if (have_posts()) : ?>')
        self.assertIn('{% if posts %}', out)

    def test_loop_becomes_for_with_post(self):
        php = '<?php while (have_posts()) : the_post(); ?>'
        out, _ = translate_template(php)
        self.assertIn('{% for post in posts %}', out)

    def test_endwhile_endif(self):
        out, _ = translate_template('<?php endwhile; endif; ?>')
        self.assertIn('{% endfor %}', out)
        self.assertIn('{% endif %}', out)

    def test_else_branch(self):
        out, _ = translate_template('<?php else : ?>')
        self.assertIn('{% else %}', out)

    def test_the_title_becomes_post_title(self):
        out, _ = translate_template('<?php the_title(); ?>')
        self.assertIn('{{ post.post_title }}', out)

    def test_the_content_uses_safe_filter(self):
        out, _ = translate_template('<?php the_content(); ?>')
        self.assertIn('{{ post.post_content|safe }}', out)

    def test_the_permalink_becomes_url_tag(self):
        out, _ = translate_template('<?php the_permalink(); ?>')
        self.assertIn("{% url 'wp_single' post.id %}", out)

    def test_the_date_uses_django_date_filter(self):
        out, _ = translate_template('<?php the_date(); ?>')
        self.assertIn('post.post_date', out)
        self.assertIn('date:', out)

    def test_the_author_resolves_via_author_obj(self):
        out, _ = translate_template('<?php the_author(); ?>')
        self.assertIn('post.author_obj.display_name', out)
        self.assertIn('default:"Anonymous"', out)

    def test_bloginfo_name(self):
        out, _ = translate_template("<?php bloginfo('name'); ?>")
        self.assertIn('{{ blog_name }}', out)

    def test_bloginfo_description(self):
        out, _ = translate_template("<?php bloginfo('description'); ?>")
        self.assertIn('{{ blog_description }}', out)

    def test_bloginfo_charset(self):
        out, _ = translate_template("<?php bloginfo('charset'); ?>")
        self.assertIn('UTF-8', out)

    def test_short_echo_home_url(self):
        out, _ = translate_template('<?= home_url() ?>')
        self.assertIn("{% url 'wp_index' %}", out)

    def test_echo_home_url(self):
        out, _ = translate_template('<?php echo home_url(); ?>')
        self.assertIn("{% url 'wp_index' %}", out)

    def test_wp_head_becomes_block(self):
        out, _ = translate_template('<?php wp_head(); ?>')
        self.assertIn('{% block extra_head %}', out)

    def test_wp_footer_becomes_block(self):
        out, _ = translate_template('<?php wp_footer(); ?>')
        self.assertIn('{% block extra_foot %}', out)

    def test_html_outside_php_passes_through(self):
        php = '<h1>Welcome</h1><?php the_title(); ?>'
        out, _ = translate_template(php)
        self.assertIn('<h1>Welcome</h1>', out)
        self.assertIn('{{ post.post_title }}', out)

    def test_unknown_function_is_flagged(self):
        php = '<?php do_my_custom_thing(); ?>'
        out, skipped = translate_template(php)
        self.assertIn('{# WP-LIFT?', out)
        self.assertEqual(len(skipped), 1)
        self.assertIn('do_my_custom_thing', skipped[0])

    def test_php_comments_are_stripped(self):
        php = '''<?php
            // This is a comment
            /* And a block comment */
            the_title();
        ?>'''
        out, skipped = translate_template(php)
        self.assertIn('{{ post.post_title }}', out)
        self.assertEqual(skipped, [])

    def test_global_post_drop_silently(self):
        php = '<?php global $post; the_title(); ?>'
        out, skipped = translate_template(php)
        self.assertIn('{{ post.post_title }}', out)
        self.assertEqual(skipped, [])

    def test_unterminated_php_block(self):
        php = '<h1>oops<?php the_title()'
        out, skipped = translate_template(php)
        self.assertIn('{# WP-LIFT?', out)
        self.assertEqual(len(skipped), 1)

    def test_static_loader_auto_prepended(self):
        php = '<link rel="stylesheet" href="<?php echo get_stylesheet_uri(); ?>">'
        out, _ = translate_template(php)
        self.assertTrue(out.startswith('{% load static %}\n'),
                        f'expected static loader at top, got: {out!r}')
        self.assertIn("{% static 'wp/style.css' %}", out)

    def test_static_loader_not_added_when_unused(self):
        php = '<?php the_title(); ?>'
        out, _ = translate_template(php)
        self.assertNotIn('{% load static %}', out)


class FullThemeTranslationTests(SimpleTestCase):
    """End-to-end on a synthetic mini-theme inside a tempdir."""

    def _make_theme(self, files: dict[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp())
        for name, body in files.items():
            (tmp / name).write_text(body, encoding='utf-8')
        return tmp

    def test_parse_theme_picks_up_standard_files(self):
        theme = self._make_theme({
            'index.php': '<?php get_header(); ?><h1>hi</h1><?php get_footer(); ?>',
            'header.php': '<!DOCTYPE html><html><head></head><body>',
            'footer.php': '</body></html>',
            'style.css': 'body { color: red; }',
        })
        result = parse_theme(theme)
        names = sorted(r.source.name for r in result.records)
        self.assertEqual(names, ['footer.php', 'header.php', 'index.php'])
        self.assertEqual([p.name for p in result.static_assets], ['style.css'])

    def test_parse_theme_flags_nonstandard_php(self):
        theme = self._make_theme({
            'index.php': '<?php get_header(); ?>',
            'functions.php': '<?php add_action("init", "my_init"); ?>',
            'shortcodes.php': '<?php add_shortcode("foo", "bar"); ?>',
        })
        result = parse_theme(theme)
        flagged = sorted(p.name for p in result.unhandled_files)
        self.assertEqual(flagged, ['functions.php', 'shortcodes.php'])

    def test_classic_loop_round_trip(self):
        loop = '''<?php get_header(); ?>
<?php if (have_posts()) : while (have_posts()) : the_post(); ?>
  <article>
    <h2><a href="<?php the_permalink(); ?>"><?php the_title(); ?></a></h2>
    <p><?php the_excerpt(); ?></p>
  </article>
<?php endwhile; else : ?>
  <p>Nothing yet.</p>
<?php endif; ?>
<?php get_footer(); ?>'''
        out, skipped = translate_template(loop)
        self.assertIn("{% include 'wp/header.html' %}", out)
        self.assertIn('{% if posts %}', out)
        self.assertIn('{% for post in posts %}', out)
        self.assertIn("{% url 'wp_single' post.id %}", out)
        self.assertIn('{{ post.post_title }}', out)
        self.assertIn('{{ post.post_excerpt }}', out)
        self.assertIn('{% endfor %}', out)
        self.assertIn('{% else %}', out)
        self.assertIn('{% endif %}', out)
        self.assertIn("{% include 'wp/footer.html' %}", out)
        self.assertEqual(skipped, [])

    def test_header_template_round_trip(self):
        header = '''<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo('charset'); ?>">
  <title><?php bloginfo('name'); ?></title>
  <link rel="stylesheet" href="<?php echo get_stylesheet_uri(); ?>">
  <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
  <header>
    <h1><a href="<?php echo home_url(); ?>"><?php bloginfo('name'); ?></a></h1>
    <p><?php bloginfo('description'); ?></p>
  </header>'''
        out, skipped = translate_template(header)
        self.assertIn('lang="en"', out)
        self.assertIn('UTF-8', out)
        self.assertIn('{{ blog_name }}', out)
        self.assertIn('{{ blog_description }}', out)
        self.assertIn("{% url 'wp_index' %}", out)
        self.assertIn("{% static 'wp/style.css' %}", out)
        self.assertIn('{% block extra_head %}', out)
        self.assertIn('class="wp"', out)
        self.assertEqual(skipped, [])


class ViewsAndUrlsGenerationTests(SimpleTestCase):

    def _theme(self, names):
        from datalift.wp_lifter import _THEME_FILE_TARGETS, TemplateRecord
        return [
            TemplateRecord(
                source=Path(n),
                target_name=_THEME_FILE_TARGETS[n][0],
                view_name=_THEME_FILE_TARGETS[n][1],
                body='',
            )
            for n in names
        ]

    def test_views_includes_index_and_single(self):
        recs = self._theme(['index.php', 'single.php'])
        text = generate_views(recs, 'wp')
        self.assertIn('def wp_index(', text)
        self.assertIn('def wp_single(', text)
        self.assertIn('"wp/index.html"', text)
        self.assertIn('"wp/single.html"', text)
        self.assertIn('post_status="publish"', text)
        self.assertIn('_attach_authors(', text)
        self.assertIn('def _attach_authors(posts):', text)

    def test_urls_includes_correct_paths(self):
        recs = self._theme(['index.php', 'single.php', 'page.php'])
        text = generate_urls(recs)
        self.assertIn("from . import views_wp as views", text)
        self.assertIn("path('', views.wp_index, name='wp_index'),", text)
        self.assertIn("path('post/<int:post_id>/'", text)
        self.assertIn("path('page/<int:page_id>/'", text)

    def test_partials_get_no_view(self):
        recs = self._theme(['header.php', 'footer.php', 'index.php'])
        text = generate_views(recs, 'wp')
        # Partials don't add new view functions, only wp_index does.
        self.assertEqual(text.count('def wp_index('), 1)
        self.assertNotIn('def wp_header(', text)


class ApplyTests(SimpleTestCase):
    """End-to-end: parse → render → write into a tempdir."""

    def test_apply_writes_templates_views_urls(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'index.php').write_text(
            '<?php get_header(); ?><h1><?php bloginfo("name"); ?></h1><?php get_footer(); ?>'
        )
        (theme / 'header.php').write_text('<!DOCTYPE html>')
        (theme / 'footer.php').write_text('</html>')
        (theme / 'style.css').write_text('body{}')

        proj = tmp / 'proj'
        (proj / 'wp').mkdir(parents=True)

        result = parse_theme(theme)
        log = apply(result, proj, 'wp')

        self.assertTrue((proj / 'templates' / 'wp' / 'index.html').exists())
        self.assertTrue((proj / 'templates' / 'wp' / 'header.html').exists())
        self.assertTrue((proj / 'templates' / 'wp' / 'footer.html').exists())
        self.assertTrue((proj / 'wp' / 'views_wp.py').exists())
        self.assertTrue((proj / 'wp' / 'urls_wp.py').exists())

        index_html = (proj / 'templates' / 'wp' / 'index.html').read_text()
        self.assertIn('{{ blog_name }}', index_html)
        self.assertIn("{% include 'wp/header.html' %}", index_html)

        urls_py = (proj / 'wp' / 'urls_wp.py').read_text()
        self.assertIn("name='wp_index'", urls_py)

        # log lines exist for each artifact
        self.assertTrue(any('template' in line for line in log))
        self.assertTrue(any('views' in line for line in log))
        self.assertTrue(any('urls' in line for line in log))

    def test_dry_run_writes_nothing(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'index.php').write_text('<?php get_header(); ?>')

        proj = tmp / 'proj'
        proj.mkdir()

        result = parse_theme(theme)
        apply(result, proj, 'wp', dry_run=True)
        self.assertFalse((proj / 'templates').exists())
        self.assertFalse((proj / 'wp').exists())


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_translated_and_unhandled(self):
        from datalift.wp_lifter import LiftResult, TemplateRecord
        result = LiftResult(
            records=[
                TemplateRecord(
                    source=Path('index.php'),
                    target_name='index.html',
                    view_name='wp_index',
                    body='',
                    skipped=['custom_loop()'],
                ),
            ],
            unhandled_files=[Path('functions.php')],
            static_assets=[Path('style.css')],
        )
        text = render_worklist(result, 'wp', Path('/tmp/theme'))
        self.assertIn('liftwp worklist', text)
        self.assertIn('`index.php`', text)
        self.assertIn('1 unhandled fragments', text)
        self.assertIn('functions.php', text)
        self.assertIn('style.css', text)
        self.assertIn('custom_loop', text)
        self.assertIn('Out of scope for Phase 1', text)

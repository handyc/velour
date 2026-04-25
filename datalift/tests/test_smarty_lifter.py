"""Tests for datalift.smarty_lifter — the Smarty → Django translator.

Each pattern surfaced during the Piwigo case study is pinned here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from datalift.smarty_lifter import (
    apply,
    parse_theme,
    render_worklist,
    translate_template,
)


class VariableEchoTests(SimpleTestCase):

    def test_bare_variable(self):
        out, _ = translate_template('{$U_HOME}')
        self.assertEqual(out.strip(), '{{ U_HOME }}')

    def test_dotted_property(self):
        out, _ = translate_template('{$post.title}')
        self.assertEqual(out.strip(), '{{ post.title }}')

    def test_arrow_property(self):
        out, _ = translate_template('{$obj->name}')
        self.assertEqual(out.strip(), '{{ obj.name }}')

    def test_array_index_string(self):
        out, _ = translate_template("{$arr['key']}")
        self.assertEqual(out.strip(), '{{ arr.key }}')

    def test_array_index_int(self):
        out, _ = translate_template('{$arr[0]}')
        self.assertEqual(out.strip(), '{{ arr.0 }}')

    def test_string_literal_translate(self):
        out, _ = translate_template("{'Home'|@translate}")
        self.assertEqual(out.strip(), 'Home')

    def test_variable_translate_filter_dropped(self):
        """`|@translate` on a variable becomes passthrough — without
        a catalog, Django can't translate at template-time anyway."""
        out, _ = translate_template('{$msg|@translate}')
        self.assertEqual(out.strip(), '{{ msg }}')


class ControlFlowTests(SimpleTestCase):

    def test_simple_if(self):
        out, _ = translate_template('{if $x}yes{/if}')
        self.assertIn('{% if x %}', out)
        self.assertIn('{% endif %}', out)

    def test_if_with_isset(self):
        out, _ = translate_template('{if isset($MENUBAR)}{$MENUBAR}{/if}')
        self.assertIn('{% if MENUBAR %}', out)
        self.assertIn('{{ MENUBAR }}', out)

    def test_if_else_endif(self):
        out, _ = translate_template('{if $x}A{else}B{/if}')
        self.assertIn('{% if x %}A{% else %}B{% endif %}', out)

    def test_if_elseif_chain(self):
        out, _ = translate_template('{if $x}1{elseif $y}2{else}3{/if}')
        self.assertIn('{% if x %}1{% elif y %}2{% else %}3{% endif %}', out)

    def test_word_operators(self):
        out, _ = translate_template('{if $x eq 5}yes{/if}')
        self.assertIn('{% if x == 5 %}', out)

    def test_not_word_operator(self):
        out, _ = translate_template('{if not $x}yes{/if}')
        self.assertIn('{% if not x %}', out)

    def test_and_or(self):
        out, _ = translate_template('{if $x and $y}yes{/if}')
        self.assertIn(' and ', out)

    def test_negation_bang(self):
        out, _ = translate_template('{if !$x}yes{/if}')
        self.assertIn('{% if not x %}', out)

    def test_empty_predicate(self):
        out, _ = translate_template('{if empty($x)}empty{/if}')
        self.assertIn('{% if not x %}', out)

    def test_foreach_modern(self):
        out, _ = translate_template('{foreach $items as $item}{$item.name}{/foreach}')
        self.assertIn('{% for item in items %}', out)
        self.assertIn('{{ item.name }}', out)
        self.assertIn('{% endfor %}', out)

    def test_foreach_with_key(self):
        out, _ = translate_template('{foreach $items as $key => $val}{$key}{/foreach}')
        self.assertIn('{% for key, val in items.items %}', out)

    def test_foreach_old_syntax(self):
        out, _ = translate_template('{foreach from=$items item=p}{$p.name}{/foreach}')
        self.assertIn('{% for p in items %}', out)
        self.assertIn('{{ p.name }}', out)

    def test_foreachelse_becomes_empty(self):
        out, _ = translate_template(
            '{foreach $items as $i}row{foreachelse}none{/foreach}'
        )
        self.assertIn('{% for i in items %}', out)
        self.assertIn('{% empty %}', out)
        self.assertIn('none', out)
        self.assertIn('{% endfor %}', out)


class IncludeTests(SimpleTestCase):

    def test_include_simple(self):
        out, _ = translate_template("{include file='header.tpl'}")
        self.assertIn("{% include 'header.html' %}", out)

    def test_include_double_quotes(self):
        out, _ = translate_template('{include file="footer.tpl"}')
        self.assertIn("{% include 'footer.html' %}", out)

    def test_include_with_extra_args(self):
        out, _ = translate_template(
            "{include file='infos_errors.tpl' lang=$LANG}"
        )
        self.assertIn("{% include 'infos_errors.html' %}", out)


class CommentLiteralTests(SimpleTestCase):

    def test_comment_dropped(self):
        out, _ = translate_template('{*this is a comment*}<p>real</p>')
        self.assertNotIn('comment', out)
        self.assertIn('<p>real</p>', out)

    def test_literal_block_passes_through(self):
        out, _ = translate_template('{literal}<style>{x:1;}</style>{/literal}')
        self.assertIn('<style>{x:1;}</style>', out)

    def test_ldelim_rdelim(self):
        out, _ = translate_template('{ldelim}body{rdelim}')
        self.assertIn('{body}', out)


class ModifierTests(SimpleTestCase):

    def test_escape_modifier(self):
        out, _ = translate_template('{$x|escape}')
        self.assertIn('{{ x|escape }}', out)

    def test_count_modifier(self):
        out, _ = translate_template('{$items|count}')
        self.assertIn('{{ items|length }}', out)

    def test_default_modifier(self):
        out, _ = translate_template("{$name|default:'Guest'}")
        self.assertIn("{{ name|default:'Guest' }}", out)

    def test_lower_modifier(self):
        out, _ = translate_template('{$x|lower}')
        self.assertIn('{{ x|lower }}', out)

    def test_capitalize_to_capfirst(self):
        out, _ = translate_template('{$x|capitalize}')
        self.assertIn('{{ x|capfirst }}', out)

    def test_date_format_to_date_filter(self):
        out, _ = translate_template('{$d|date_format:"%Y-%m-%d"}')
        self.assertIn('{{ d|date:"Y-m-d" }}', out)

    def test_url_encode_modifier(self):
        out, _ = translate_template('{$url|@urlencode}')
        self.assertIn('{{ url|urlencode }}', out)

    def test_modifier_chain(self):
        out, _ = translate_template('{$x|lower|escape}')
        self.assertIn('{{ x|lower|escape }}', out)


class IgnoredTagsTests(SimpleTestCase):

    def test_strip_drops(self):
        out, _ = translate_template('{strip}\n  hello  \n{/strip}')
        self.assertIn('hello', out)
        # The strip wrapper itself should not appear in output.
        self.assertNotIn('{strip}', out)
        self.assertNotIn('{/strip}', out)

    def test_nocache_drops(self):
        out, _ = translate_template('{nocache}content{/nocache}')
        self.assertIn('content', out)
        self.assertNotIn('nocache', out)

    def test_truly_unknown_tag_flagged(self):
        out, skipped = translate_template('{wibble_wobble foo=$bar}')
        self.assertIn('SMARTY-LIFT?', out)
        self.assertEqual(len(skipped), 1)

    def test_known_plugin_emits_porter_marker_not_skipped(self):
        """Known Smarty stdlib / Piwigo-style block plugins (html_image,
        combine_script, footer_script, etc.) emit a quiet porter comment
        rather than landing in the worklist."""
        for name in ('html_image src="foo.jpg"', 'combine_script id="x"',
                     'footer_script require="jquery"'):
            out, skipped = translate_template('{' + name + '}')
            self.assertEqual(skipped, [], f'{name!r} got skipped')
            self.assertIn('smarty plugin', out)


class WalkerTests(SimpleTestCase):

    def test_parse_theme_picks_up_tpl(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'header.tpl').write_text("<h1>{$blog_name}</h1>")
        (theme / 'footer.tpl').write_text("&copy; {$year}")
        (theme / 'index.php').write_text("<?php // theme entrypoint ?>")
        (theme / 'style.css').write_text("body{}")

        result = parse_theme(theme)
        names = sorted(r.source.name for r in result.records)
        self.assertEqual(names, ['footer.tpl', 'header.tpl'])
        self.assertEqual([p.name for p in result.unhandled_files], ['index.php'])
        self.assertEqual([p.name for p in result.static_assets], ['style.css'])

    def test_parse_theme_preserves_subdir_paths(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        (theme / 'template').mkdir(parents=True)
        (theme / 'template' / 'menubar.tpl').write_text('{$x}')
        result = parse_theme(theme)
        names = sorted(r.target_name for r in result.records)
        self.assertEqual(names, ['template/menubar.html'])

    def test_apply_writes_translated_html(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'theme'
        theme.mkdir()
        (theme / 'identification.tpl').write_text(
            "{if isset($U_HOME)}<a href=\"{$U_HOME}\">{'Home'|@translate}</a>{/if}"
        )
        proj = tmp / 'proj'
        proj.mkdir()
        result = parse_theme(theme)
        apply(result, proj, 'gallery')
        body = (proj / 'templates' / 'gallery' / 'identification.html').read_text()
        self.assertIn('{% if U_HOME %}', body)
        self.assertIn('{{ U_HOME }}', body)
        self.assertIn('Home', body)
        self.assertIn('{% endif %}', body)


class WorklistTests(SimpleTestCase):

    def test_worklist_lists_translated_and_unhandled(self):
        from datalift.smarty_lifter import LiftResult, TemplateRecord
        result = LiftResult(
            records=[
                TemplateRecord(
                    source=Path('header.tpl'),
                    target_name='header.html',
                    body='',
                    skipped=['html_image src="foo"'],
                ),
            ],
            unhandled_files=[Path('themeconf.inc.php')],
            static_assets=[Path('css/style.css')],
        )
        text = render_worklist(result, 'gallery', Path('/tmp/theme'))
        self.assertIn('liftsmarty worklist', text)
        self.assertIn('header.tpl', text)
        self.assertIn('1 unhandled fragments', text)
        self.assertIn('themeconf.inc.php', text)
        self.assertIn('html_image', text)


class PiwigoSampleTests(SimpleTestCase):
    """Translate the actual Piwigo identification.tpl as the sample
    used in the Piwigo case study."""

    SAMPLE = """{if isset($MENUBAR)}{$MENUBAR}{/if}
<div id="content" class="content{if isset($MENUBAR)} contentWithMenu{/if}">

<div class="titrePage">
<ul class="categoryActions"></ul>
<h2><a href="{$U_HOME}">{'Home'|@translate}</a>{$LEVEL_SEPARATOR}{'Identification'|@translate}</h2>
</div>

{include file='infos_errors.tpl'}

<form action="{$F_LOGIN_ACTION}" method="post" name="login_form" class="properties">
<input type="hidden" name="redirect" value="{$U_REDIRECT|@urlencode}">
{if $authorize_remembering }
<input type="checkbox" name="remember_me">
{/if}
{if isset($U_REGISTER)}
<a href="{$U_REGISTER}">{'Register'|@translate}</a>
{/if}
</form>"""

    def test_full_translate_clean(self):
        out, skipped = translate_template(self.SAMPLE)
        self.assertEqual(skipped, [], f'unexpected skipped: {skipped}')
        # Spot checks across the translated body
        self.assertIn('{% if MENUBAR %}', out)
        self.assertIn('{{ MENUBAR }}', out)
        self.assertIn('{{ U_HOME }}', out)
        self.assertIn('Home', out)
        self.assertIn('{{ LEVEL_SEPARATOR }}', out)
        self.assertIn("{% include 'infos_errors.html' %}", out)
        self.assertIn('{{ F_LOGIN_ACTION }}', out)
        self.assertIn('{{ U_REDIRECT|urlencode }}', out)
        self.assertIn('{% if authorize_remembering %}', out)
        self.assertIn('Register', out)
        self.assertIn('{% endif %}', out)

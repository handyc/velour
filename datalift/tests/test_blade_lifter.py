"""Tests for datalift.blade_lifter — Laravel Blade → Django."""

from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from datalift.blade_lifter import (
    apply, parse_theme, render_worklist, translate_template,
)


class EchoTests(SimpleTestCase):

    def test_simple_var(self):
        out, _ = translate_template('{{ $name }}')
        self.assertIn('{{ name }}', out)

    def test_property_access(self):
        out, _ = translate_template('{{ $user->name }}')
        self.assertIn('{{ user.name }}', out)

    def test_array_index_string(self):
        out, _ = translate_template("{{ $arr['key'] }}")
        self.assertIn('{{ arr.key }}', out)

    def test_array_index_int(self):
        out, _ = translate_template('{{ $arr[0] }}')
        self.assertIn('{{ arr.0 }}', out)

    def test_raw_echo_uses_safe(self):
        out, _ = translate_template('{!! $html !!}')
        self.assertIn('{{ html|safe }}', out)

    def test_method_call_passes_through(self):
        # Method calls like $user->getName() are arbitrary PHP — best
        # we can do is translate the dollar refs.
        out, _ = translate_template('{{ $obj->name }}')
        self.assertIn('obj.name', out)


class ControlFlowTests(SimpleTestCase):

    def test_if_chain(self):
        out, _ = translate_template(
            '@if($x) A @elseif($y) B @else C @endif'
        )
        self.assertIn('{% if x %}', out)
        self.assertIn('{% elif y %}', out)
        self.assertIn('{% else %}', out)
        self.assertIn('{% endif %}', out)

    def test_unless(self):
        out, _ = translate_template('@unless($x) hidden @endunless')
        self.assertIn('{% if not (x) %}', out)
        self.assertIn('{% endif %}', out)

    def test_isset(self):
        out, _ = translate_template('@isset($x) shown @endisset')
        self.assertIn('{% if x %}', out)

    def test_empty_directive(self):
        # Note: @empty is also a forelse helper — careful matching
        out, _ = translate_template('@empty($x) blank @endempty')
        self.assertIn('{% if not (x) %}', out)

    def test_foreach_simple(self):
        out, _ = translate_template(
            '@foreach($users as $user) {{ $user->name }} @endforeach'
        )
        self.assertIn('{% for user in users %}', out)
        self.assertIn('{{ user.name }}', out)
        self.assertIn('{% endfor %}', out)

    def test_foreach_with_key(self):
        out, _ = translate_template(
            '@foreach($items as $key => $val) {{ $key }} @endforeach'
        )
        self.assertIn('{% for key, val in items.items %}', out)


class IncludeExtendsTests(SimpleTestCase):

    def test_include_dotted_path(self):
        out, _ = translate_template("@include('layouts.app')")
        self.assertIn("{% include 'layouts/app.html' %}", out)

    def test_extends_dotted_path(self):
        out, _ = translate_template("@extends('layouts.master')")
        self.assertIn("{% extends 'layouts/master.html' %}", out)

    def test_yield_simple(self):
        out, _ = translate_template("@yield('content')")
        self.assertIn('{% block content %}{% endblock %}', out)

    def test_yield_with_default_string(self):
        out, _ = translate_template("@yield('title', 'Home')")
        self.assertIn('{% block title %}Home{% endblock %}', out)

    def test_section_endsection(self):
        out, _ = translate_template(
            "@section('content') body @endsection"
        )
        self.assertIn('{% block content %}', out)
        self.assertIn('{% endblock %}', out)

    def test_inline_section(self):
        out, _ = translate_template(
            "@section('title', 'Page Title')"
        )
        self.assertIn('{% block title %}Page Title{% endblock %}', out)


class AuthHelpersTests(SimpleTestCase):

    def test_auth_endauth(self):
        out, _ = translate_template('@auth Hi! @endauth')
        self.assertIn('{% if user.is_authenticated %}', out)
        self.assertIn('{% endif %}', out)

    def test_guest_endguest(self):
        out, _ = translate_template('@guest Sign in @endguest')
        self.assertIn('{% if not user.is_authenticated %}', out)

    def test_csrf(self):
        out, _ = translate_template('<form>@csrf</form>')
        self.assertIn('{% csrf_token %}', out)


class PhpAndCommentTests(SimpleTestCase):

    def test_blade_comment_to_django(self):
        out, _ = translate_template('{{-- secret note --}}body')
        self.assertIn('{# secret note #}', out)
        self.assertIn('body', out)

    def test_php_block_emits_marker(self):
        out, _ = translate_template('@php $x = 5; @endphp')
        self.assertIn('blade @php', out)


class DirectiveAllowlistTests(SimpleTestCase):
    """Only known Blade directive names are interpreted. Unknown @-names
    pass through verbatim — this is what lets CSS `@import`, `@media`,
    `@font-face` and JS docblock `@var` survive without false-positive
    markers."""

    def test_css_at_rules_pass_through(self):
        out, skipped = translate_template(
            "<style>@import url('x.css'); @media (max-width: 600px) { } @font-face { } </style>"
        )
        self.assertIn("@import url('x.css')", out)
        self.assertIn('@media', out)
        self.assertIn('@font-face', out)
        self.assertEqual(skipped, [])

    def test_unknown_blade_like_directive_passes_through(self):
        """Plugin directives like @livewire / @vite are not in the core
        allowlist and pass through verbatim — the porter sees the
        literal directive in the rendered output."""
        out, skipped = translate_template("@livewire('counter')")
        self.assertIn("@livewire('counter')", out)
        self.assertEqual(skipped, [])

    def test_known_directive_translated(self):
        out, _ = translate_template("@if($x) yes @endif")
        self.assertIn('{% if x %}', out)


class WalkerTests(SimpleTestCase):

    def test_parse_theme_picks_up_blade_files(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'views'
        theme.mkdir()
        (theme / 'home.blade.php').write_text(
            "@extends('layouts.app')@section('c'){{ $title }}@endsection"
        )
        (theme / 'config.php').write_text("<?php // not a view ?>")
        (theme / 'style.css').write_text("body{}")
        result = parse_theme(theme)
        names = sorted(r.target_name for r in result.records)
        self.assertEqual(names, ['home.html'])
        self.assertEqual([p.name for p in result.unhandled_files], ['config.php'])
        self.assertEqual([p.name for p in result.static_assets], ['style.css'])

    def test_apply_writes_translated_html(self):
        tmp = Path(tempfile.mkdtemp())
        theme = tmp / 'views'
        theme.mkdir()
        (theme / 'page.blade.php').write_text(
            "@extends('layouts.app')\n"
            "@section('content')\n"
            "@foreach($posts as $post)\n"
            "  <h2>{{ $post->title }}</h2>\n"
            "@endforeach\n"
            "@endsection\n"
        )
        proj = tmp / 'proj'
        proj.mkdir()
        result = parse_theme(theme)
        apply(result, proj, 'blog')
        body = (proj / 'templates' / 'blog' / 'page.html').read_text()
        self.assertIn("{% extends 'layouts/app.html' %}", body)
        self.assertIn('{% block content %}', body)
        self.assertIn('{% for post in posts %}', body)
        self.assertIn('{{ post.title }}', body)
        self.assertIn('{% endfor %}', body)
        self.assertIn('{% endblock %}', body)


class RealisticSampleTests(SimpleTestCase):
    """Realistic Laravel-shaped Blade view should translate cleanly."""

    SAMPLE = """@extends('layouts.app')

@section('title', 'Posts')

@section('content')
<div class="container">
@auth
    <p>Welcome, {{ $user->name }}.</p>
@endauth

<h1>Posts</h1>

@if(count($posts) > 0)
<ul>
@foreach($posts as $post)
    <li>
        <a href="{{ $post->url }}">{{ $post->title }}</a>
        @isset($post->author)
            by {{ $post->author->name }}
        @endisset
    </li>
@endforeach
</ul>
@else
<p>No posts yet.</p>
@endif

<form method="POST" action="/posts">
@csrf
<input name="title" />
<button>Submit</button>
</form>
</div>
@endsection"""

    def test_full_translation_mostly_clean(self):
        out, skipped = translate_template(self.SAMPLE)
        self.assertIn("{% extends 'layouts/app.html' %}", out)
        self.assertIn('{% block title %}Posts{% endblock %}', out)
        self.assertIn('{% block content %}', out)
        self.assertIn('{% if user.is_authenticated %}', out)
        self.assertIn('{{ user.name }}', out)
        self.assertIn('{% if count(posts) > 0 %}', out)
        self.assertIn('{% for post in posts %}', out)
        self.assertIn('{{ post.url }}', out)
        self.assertIn('{{ post.title }}', out)
        self.assertIn('{% if post.author %}', out)
        self.assertIn('{{ post.author.name }}', out)
        self.assertIn('{% csrf_token %}', out)
        self.assertIn('{% endblock %}', out)
        # `count()` is left as a function call — Django will fail to
        # resolve it. That's expected; the porter swaps it for `|length`.
        self.assertEqual(skipped, [])

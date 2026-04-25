"""Tests for datalift.php_code_lifter — generic PHP → Python."""

from __future__ import annotations

import tempfile
from pathlib import Path
from textwrap import dedent

from django.test import SimpleTestCase

from datalift.php_code_lifter import (
    apply, parse_file, parse_php_code, render_python,
    _translate_expr, _translate_block, _translate_simple_statement,
)


class ExpressionTests(SimpleTestCase):

    def test_dollar_strip(self):
        self.assertEqual(_translate_expr('$x + $y'), 'x + y')

    def test_null_true_false(self):
        self.assertEqual(_translate_expr('$x === null'), 'x == None')
        self.assertEqual(_translate_expr('true || false'), 'True or False')

    def test_string_concat(self):
        self.assertEqual(_translate_expr("'a' . 'b'"), "'a' + 'b'")

    def test_string_concat_var(self):
        self.assertEqual(_translate_expr("$s . '!'"), "s + '!'")

    def test_logical(self):
        self.assertEqual(_translate_expr('$a && $b'), 'a and b')
        self.assertEqual(_translate_expr('$a || $b'), 'a or b')

    def test_not(self):
        self.assertEqual(_translate_expr('!$x'), 'not x')

    def test_neq(self):
        self.assertEqual(_translate_expr('$x !== null'), 'x != None')

    def test_object_access(self):
        self.assertEqual(_translate_expr('$user->name'), 'user.name')

    def test_static_call(self):
        self.assertEqual(_translate_expr('Foo::bar()'), 'Foo.bar()')

    def test_self_keyword(self):
        self.assertEqual(_translate_expr('self::foo()'), 'self.foo()')

    def test_class_constant(self):
        self.assertEqual(_translate_expr('Foo::class'), 'Foo')

    def test_isset(self):
        self.assertEqual(_translate_expr('isset($x)'), '(x is not None)')

    def test_empty(self):
        self.assertEqual(_translate_expr('empty($arr)'), '(not arr)')

    def test_new(self):
        self.assertEqual(_translate_expr('new Foo()'), 'Foo()')

    def test_null_coalesce(self):
        self.assertEqual(_translate_expr('$x ?? "default"'),
                          'x or "default"')

    def test_strlen_to_len(self):
        self.assertIn('len(', _translate_expr('strlen($s)'))

    def test_count_to_len(self):
        self.assertIn('len(', _translate_expr('count($arr)'))

    def test_explode(self):
        self.assertEqual(_translate_expr("explode(',', $s)"),
                          "s.split(',')")

    def test_implode(self):
        self.assertEqual(_translate_expr("implode(',', $arr)"),
                          "','.join(arr)")

    def test_array_keys(self):
        self.assertEqual(_translate_expr("array_keys($x)"),
                          "list(x.keys())")

    def test_in_array(self):
        self.assertEqual(_translate_expr("in_array($x, $arr)"),
                          "(x in arr)")

    def test_strpos(self):
        self.assertIn('.find(', _translate_expr("strpos($s, 'foo')"))

    def test_str_replace(self):
        self.assertIn('.replace(', _translate_expr(
            "str_replace('a', 'b', $s)"))

    def test_json_encode(self):
        self.assertIn('json.dumps', _translate_expr('json_encode($x)'))


class StatementTests(SimpleTestCase):

    def test_assign(self):
        self.assertEqual(_translate_simple_statement('$x = 5'), 'x = 5')

    def test_array_push(self):
        self.assertEqual(_translate_simple_statement('$arr[] = 1'),
                          'arr.append(1)')

    def test_array_assign(self):
        self.assertEqual(_translate_simple_statement("$arr['k'] = 1"),
                          "arr['k'] = 1")

    def test_return(self):
        self.assertEqual(_translate_simple_statement('return $x'),
                          'return x')

    def test_return_empty(self):
        self.assertEqual(_translate_simple_statement('return'), 'return')

    def test_throw(self):
        self.assertEqual(_translate_simple_statement('throw new Exception()'),
                          'raise Exception()')

    def test_echo(self):
        self.assertIn('print(', _translate_simple_statement('echo $msg'))

    def test_break(self):
        self.assertEqual(_translate_simple_statement('break'), 'break')


class BlockTranslationTests(SimpleTestCase):

    def test_if_else(self):
        php = "if ($x > 0) { $y = 1; } else { $y = 2; }"
        out = _translate_block(php)
        self.assertIn('if x > 0:', out)
        self.assertIn('else:', out)
        self.assertIn('y = 1', out)
        self.assertIn('y = 2', out)

    def test_elseif_chain(self):
        php = ("if ($x == 1) { $y = 'a'; } "
               "elseif ($x == 2) { $y = 'b'; } "
               "else { $y = 'c'; }")
        out = _translate_block(php)
        self.assertIn('if x == 1:', out)
        self.assertIn('elif x == 2:', out)
        self.assertIn('else:', out)

    def test_foreach_value(self):
        php = "foreach ($items as $item) { echo $item; }"
        out = _translate_block(php)
        self.assertIn('for item in items:', out)
        self.assertIn('print(item)', out)

    def test_foreach_key_value(self):
        php = "foreach ($map as $k => $v) { echo $k; }"
        out = _translate_block(php)
        self.assertIn('for k, v in map.items():', out)

    def test_for_classic(self):
        php = "for ($i = 0; $i < 10; $i++) { echo $i; }"
        out = _translate_block(php)
        self.assertIn('for i in range(0, 10):', out)

    def test_while(self):
        php = "while ($x > 0) { $x = $x - 1; }"
        out = _translate_block(php)
        self.assertIn('while x > 0:', out)
        self.assertIn('x = x - 1', out)

    def test_try_catch(self):
        php = ("try { foo(); } "
               "catch (Exception $e) { echo $e; } "
               "catch (\\Foo\\Bar $e) { echo 'bar'; }")
        out = _translate_block(php)
        self.assertIn('try:', out)
        self.assertIn('except Exception as e:', out)
        self.assertIn('except Foo.Bar as e:', out)

    def test_switch(self):
        php = ("switch ($x) { case 1: echo 'one'; break; "
               "case 2: echo 'two'; break; default: echo '?'; }")
        out = _translate_block(php)
        self.assertIn('match x:', out)
        self.assertIn('case 1:', out)
        self.assertIn('case 2:', out)
        self.assertIn('case _:', out)

    def test_local_function(self):
        php = "function helper($a, $b = 1) { return $a + $b; }"
        out = _translate_block(php)
        self.assertIn('def helper(a, b=1):', out)
        self.assertIn('return a + b', out)


class FileParseTests(SimpleTestCase):

    def test_class_with_methods(self):
        php = dedent("""\
            <?php
            namespace App;
            class Greeter {
                public string $name = 'World';
                public function greet(): string {
                    return 'Hello ' . $this->name;
                }
            }
        """)
        rec = parse_file(php)
        self.assertEqual(rec.namespace, 'App')
        self.assertEqual(len(rec.classes), 1)
        cls = rec.classes[0]
        self.assertEqual(cls.name, 'Greeter')
        self.assertEqual(len(cls.properties), 1)
        self.assertEqual(cls.properties[0].name, 'name')
        self.assertEqual(len(cls.methods), 1)
        self.assertEqual(cls.methods[0].name, 'greet')

    def test_class_inheritance(self):
        php = dedent("""\
            <?php
            class Foo extends \\App\\Bar implements Baz, Qux {
                public function f() {}
            }
        """)
        rec = parse_file(php)
        self.assertEqual(rec.classes[0].parent, 'App.Bar')
        self.assertEqual(rec.classes[0].interfaces, ['Baz', 'Qux'])

    def test_top_level_function(self):
        php = dedent("""\
            <?php
            function add($a, $b) { return $a + $b; }
        """)
        rec = parse_file(php)
        self.assertEqual(len(rec.functions), 1)
        self.assertEqual(rec.functions[0].name, 'add')
        self.assertEqual(rec.functions[0].args, ['a', 'b'])

    def test_function_inside_class_not_doubled(self):
        php = dedent("""\
            <?php
            class C { public function m() {} }
            function topfn() {}
        """)
        rec = parse_file(php)
        self.assertEqual(len(rec.functions), 1)
        self.assertEqual(rec.functions[0].name, 'topfn')

    def test_constants(self):
        php = dedent("""\
            <?php
            class C {
                const VERSION = '1.0';
                public function m() {}
            }
        """)
        rec = parse_file(php)
        self.assertEqual(rec.classes[0].constants, [('VERSION', "'1.0'")])

    def test_default_param_translated(self):
        php = dedent("""\
            <?php
            function greet($name = 'World') { return 'Hi ' . $name; }
        """)
        rec = parse_file(php)
        self.assertEqual(rec.functions[0].args, ["name='World'"])


class RenderTests(SimpleTestCase):

    def test_render_class(self):
        from datalift.php_code_lifter import (
            PhpFile, PhpClass, PhpFunction, PhpProperty,
        )
        rec = PhpFile(
            source=Path('Foo.php'),
            classes=[PhpClass(
                name='Foo',
                properties=[PhpProperty(name='x', visibility='public',
                                         default='1')],
                methods=[PhpFunction(name='bar', args=['self'],
                                      body_python='        return self.x',
                                      body_php='return $this->x;')],
            )],
        )
        out = render_python(rec)
        self.assertIn('class Foo:', out)
        self.assertIn('def bar(self):', out)
        self.assertIn('x = 1', out)


class WalkerTests(SimpleTestCase):

    def test_skips_vendor(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'src').mkdir()
        (tmp / 'vendor').mkdir()
        (tmp / 'src' / 'a.php').write_text("<?php function a() {}")
        (tmp / 'vendor' / 'b.php').write_text("<?php function b() {}")
        result = parse_php_code(tmp)
        names = sorted(str(f.source) for f in result.files)
        self.assertEqual(names, ['src/a.php'])


class ApplyTests(SimpleTestCase):

    def test_apply_writes_mirror_tree(self):
        from datalift.php_code_lifter import (
            PhpCodeLiftResult, PhpFile, PhpFunction,
        )
        tmp = Path(tempfile.mkdtemp())
        proj = tmp / 'proj'; proj.mkdir()
        result = PhpCodeLiftResult(files=[
            PhpFile(source=Path('lib/util.php'),
                    functions=[PhpFunction(
                        name='hello', args=[],
                        body_python='    return 1', body_php='return 1;',
                    )]),
        ])
        apply(result, proj, 'myapp')
        path = proj / 'myapp' / 'php_lifted' / 'lib' / 'util.py'
        body = path.read_text()
        self.assertIn('def hello():', body)

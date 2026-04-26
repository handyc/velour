"""Translate PHP source to Python via tree-sitter-php AST.

This is the "real parser" sibling of `php_code_lifter`. Where the
catch-all uses a regex pipeline (which bottoms out around 53-66%
compile rate on real corpora — see the LimeSurvey / MediaWiki /
phpBB case studies), this module walks an actual PHP AST emitted
by tree-sitter-php.

Architecture: one visitor function per AST node type. The PHP
grammar in tree-sitter-php has ~150 node types; the common code
in real PHP uses ~50. This module covers the common path; nodes
it doesn't recognise emit a `# PORTER:` marker with the original
source so the porter has visible failure cases.

Pipeline integration: `liftphpcode` calls this module FIRST. If
tree-sitter parsing succeeds and the visitor recognises every
top-level node, the AST output is used. Otherwise it falls back
to the regex catch-all.

Pure Python (apart from tree-sitter's bundled C parser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tree_sitter_php as _tsp
    from tree_sitter import Language, Parser
    _PHP = Language(_tsp.language_php())
    _PARSER = Parser(_PHP)
    AVAILABLE = True
except Exception:
    AVAILABLE = False
    _PARSER = None


# ── Records ────────────────────────────────────────────────────────

@dataclass
class AstLiftResult:
    python: str
    porter_markers: int = 0
    unrecognised_nodes: list[str] = field(default_factory=list)


# ── Public entry ──────────────────────────────────────────────────

def parse(php_src: bytes | str) -> AstLiftResult | None:
    """Parse a PHP source string and return Python source.

    Returns None if tree-sitter-php is unavailable or the parse
    fails fundamentally. Otherwise always returns a result, even
    if it contains porter markers."""
    if not AVAILABLE or _PARSER is None:
        return None
    if isinstance(php_src, str):
        php_src = php_src.encode('utf-8', errors='replace')
    tree = _PARSER.parse(php_src)
    visitor = _Visitor(php_src)
    py = visitor.visit(tree.root_node, 0)
    return AstLiftResult(
        python=py,
        porter_markers=visitor.porter_count,
        unrecognised_nodes=visitor.unrecognised,
    )


def parse_file(path: Path) -> AstLiftResult | None:
    try:
        return parse(path.read_bytes())
    except OSError:
        return None


# ── PHP keywords that collide with Python ─────────────────────────

_PY_KEYWORDS = frozenset((
    'False', 'None', 'True', 'and', 'as', 'assert', 'async', 'await',
    'break', 'class', 'continue', 'def', 'del', 'elif', 'else',
    'except', 'finally', 'for', 'from', 'global', 'if', 'import',
    'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise',
    'return', 'try', 'while', 'with', 'yield', 'match', 'case',
))


def _safe_name(name: str) -> str:
    """Suffix `_` to identifiers that collide with Python keywords."""
    return name + '_' if name in _PY_KEYWORDS else name


# ── Common-PHP-function → Python mapping ──────────────────────────

_PHP_TO_PY = {
    'strlen': 'len', 'count': 'len', 'sizeof': 'len',
    'strtolower': lambda a: f'{a[0]}.lower()' if a else None,
    'strtoupper': lambda a: f'{a[0]}.upper()' if a else None,
    'trim': lambda a: f'{a[0]}.strip()' if a else None,
    'ltrim': lambda a: f'{a[0]}.lstrip()' if a else None,
    'rtrim': lambda a: f'{a[0]}.rstrip()' if a else None,
    'str_replace': lambda a: f'{a[2]}.replace({a[0]}, {a[1]})' if len(a) == 3 else None,
    'str_contains': lambda a: f'({a[1]} in {a[0]})' if len(a) == 2 else None,
    'str_starts_with': lambda a: f'{a[0]}.startswith({a[1]})' if len(a) == 2 else None,
    'str_ends_with': lambda a: f'{a[0]}.endswith({a[1]})' if len(a) == 2 else None,
    'explode': lambda a: f'{a[1]}.split({a[0]})' if len(a) == 2 else None,
    'implode': lambda a: f'{a[0]}.join({a[1]})' if len(a) == 2 else f"''.join({a[0]})",
    'in_array': lambda a: f'({a[0]} in {a[1]})' if len(a) >= 2 else None,
    'array_keys': lambda a: f'list({a[0]}.keys())' if a else None,
    'array_values': lambda a: f'list({a[0]}.values())' if a else None,
    'array_map': lambda a: f'list(map({a[0]}, {a[1]}))' if len(a) == 2 else None,
    'array_filter': lambda a: f'list(filter({a[1]}, {a[0]}))' if len(a) == 2 else f'[x for x in {a[0]} if x]',
    'array_merge': lambda a: f'{{**{a[0]}, **{a[1]}}}' if len(a) == 2 else f'({" + ".join(a)})',
    'array_unique': lambda a: f'list(dict.fromkeys({a[0]}))' if a else None,
    'array_reverse': lambda a: f'list(reversed({a[0]}))' if a else None,
    'array_key_exists': lambda a: f'({a[0]} in {a[1]})' if len(a) == 2 else None,
    'is_array': lambda a: f'isinstance({a[0]}, list)' if a else None,
    'is_string': lambda a: f'isinstance({a[0]}, str)' if a else None,
    'is_int': lambda a: f'isinstance({a[0]}, int)' if a else None,
    'is_null': lambda a: f'({a[0]} is None)' if a else None,
    'json_encode': lambda a: f'json.dumps({a[0]})' if a else None,
    'json_decode': lambda a: f'json.loads({a[0]})' if a else None,
    'md5': lambda a: f'hashlib.md5({a[0]}.encode()).hexdigest()' if a else None,
    'sha1': lambda a: f'hashlib.sha1({a[0]}.encode()).hexdigest()' if a else None,
    'echo': 'print', 'print_r': lambda a: f'print({a[0]})' if a else None,
    'die': lambda a: f'sys.exit({a[0]})' if a else 'sys.exit()',
    'exit': lambda a: f'sys.exit({a[0]})' if a else 'sys.exit()',
    'time': lambda a: 'int(time.time())',
    'preg_match': lambda a: f're.search({a[0]}, {a[1]})' if len(a) >= 2 else None,
    'preg_replace': lambda a: f're.sub({a[0]}, {a[1]}, {a[2]})' if len(a) == 3 else None,
    'preg_split': lambda a: f're.split({a[0]}, {a[1]})' if len(a) >= 2 else None,
    'sprintf': lambda a: f'({a[0]} % ({", ".join(a[1:])}))' if len(a) >= 2 else (a[0] if a else "''"),
    'intval': 'int', 'floatval': 'float', 'strval': 'str', 'boolval': 'bool',
    'abs': 'abs', 'min': 'min', 'max': 'max', 'round': 'round',
    'array_sum': lambda a: f'sum({a[0]})' if a else None,
}


# ── PHP type cast → Python constructor ────────────────────────────

_CAST_TYPE = {
    'int': 'int', 'integer': 'int',
    'float': 'float', 'double': 'float', 'real': 'float',
    'string': 'str',
    'bool': 'bool', 'boolean': 'bool',
    'array': 'list',
    'object': 'dict',
}


# ── Visitor ───────────────────────────────────────────────────────

class _Visitor:
    """Walks a tree-sitter PHP AST and emits Python source."""

    def __init__(self, src: bytes) -> None:
        self.src = src
        self.porter_count = 0
        self.unrecognised: list[str] = []
        self._anon_counter = 0

    def text(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode(
            'utf-8', errors='replace')

    def porter(self, node, message: str = '') -> str:
        self.porter_count += 1
        return f'# PORTER: {message or node.type}: {self.text(node)[:60]!r}'

    def unknown(self, node, indent: int) -> str:
        if node.type not in self.unrecognised:
            self.unrecognised.append(node.type)
        pad = '    ' * indent
        return f'{pad}{self.porter(node)}'

    # ── Dispatch ──────────────────────────────────────────────────

    def visit(self, node, indent: int) -> str:
        method = getattr(self, f'visit_{node.type}', None)
        if method is not None:
            return method(node, indent)
        return self.unknown(node, indent)

    # ── Top-level ─────────────────────────────────────────────────

    def visit_program(self, node, indent: int) -> str:
        out: list[str] = [
            '"""Auto-translated from PHP source by datalift php_ast_lifter."""',
            'from __future__ import annotations',
            'import sys, os, math, json, re, hashlib, base64, urllib.parse, html, time, datetime, functools',
            '# PHP-semantics shims: php_isset, php_empty, php_eq, php_count,',
            '# PhpArray, ob_start/ob_get_clean, the superglobals (_GET/_POST/...).',
            'from datalift.php_runtime import *  # noqa: F401, F403',
            '',
        ]
        for child in node.children:
            if child.type in ('php_tag', '?>'):
                continue
            piece = self.visit(child, indent)
            if piece.strip():
                out.append(piece)
        return '\n'.join(out)

    def visit_text(self, node, indent: int) -> str:
        # Inline HTML/text outside `<?php ... ?>`
        return ''

    def visit_comment(self, node, indent: int) -> str:
        return ''

    def visit_namespace_definition(self, node, indent: int) -> str:
        ns = node.child_by_field_name('name')
        if ns is None:
            return ''
        return f'# Original PHP namespace: {self.text(ns)}'

    def visit_namespace_use_declaration(self, node, indent: int) -> str:
        return f'# {self.text(node)}'

    # ── Class / function declarations ─────────────────────────────

    def visit_class_declaration(self, node, indent: int) -> str:
        name_node = node.child_by_field_name('name')
        name = self.text(name_node) if name_node else 'AnonClass'
        bases: list[str] = []
        # Walk children for `extends`/`implements` clauses.
        for c in node.children:
            if c.type == 'base_clause':
                for cc in c.children:
                    if cc.type in ('name', 'qualified_name'):
                        bases.append(self.text(cc).replace('\\', '.').lstrip('.'))
            elif c.type == 'class_interface_clause':
                for cc in c.children:
                    if cc.type in ('name', 'qualified_name'):
                        bases.append(self.text(cc).replace('\\', '.').lstrip('.'))
        body = node.child_by_field_name('body')
        body_lines: list[str] = []
        if body is not None:
            for c in body.children:
                if c.type in ('{', '}', 'comment'):
                    continue
                piece = self.visit(c, indent + 1)
                if piece.strip():
                    body_lines.append(piece)
        bclause = f'({", ".join(bases)})' if bases else ''
        pad = '    ' * indent
        body_py = '\n'.join(body_lines) or f'{pad}    pass'
        return f'{pad}class {name}{bclause}:\n{body_py}'

    def visit_interface_declaration(self, node, indent: int) -> str:
        # Treat as abstract base class for now.
        return self.visit_class_declaration(node, indent)

    def visit_trait_declaration(self, node, indent: int) -> str:
        return self.visit_class_declaration(node, indent)

    def visit_enum_declaration(self, node, indent: int) -> str:
        # Translate to a Python class with class-level constants.
        return self.visit_class_declaration(node, indent)

    def visit_property_declaration(self, node, indent: int) -> str:
        # `public string $name = 'World';`
        out: list[str] = []
        for c in node.children:
            if c.type == 'property_element':
                # Children: variable_name, optional `= expr`
                name = ''
                default = 'None'
                got_eq = False
                for pc in c.children:
                    if pc.type == 'variable_name':
                        name = self.text(pc).lstrip('$')
                    elif pc.type == '=':
                        got_eq = True
                    elif got_eq:
                        default = self.visit_expr(pc)
                if name:
                    out.append('    ' * indent + f'{_safe_name(name)} = {default}')
        return '\n'.join(out)

    def visit_const_declaration(self, node, indent: int) -> str:
        out: list[str] = []
        for c in node.children:
            if c.type == 'const_element':
                name = ''
                value = 'None'
                got_eq = False
                for cc in c.children:
                    if cc.type == 'name':
                        name = self.text(cc)
                    elif cc.type == '=':
                        got_eq = True
                    elif got_eq:
                        value = self.visit_expr(cc)
                if name:
                    out.append('    ' * indent + f'{_safe_name(name)} = {value}')
        return '\n'.join(out)

    def visit_method_declaration(self, node, indent: int) -> str:
        return self._visit_function_like(node, indent, is_method=True)

    def visit_function_definition(self, node, indent: int) -> str:
        return self._visit_function_like(node, indent, is_method=False)

    def _visit_function_like(self, node, indent: int, is_method: bool) -> str:
        name_node = node.child_by_field_name('name')
        name = self.text(name_node) if name_node else 'anon'
        params_node = node.child_by_field_name('parameters')
        is_static = any(
            c.type == 'static_modifier'
            or (c.type == 'visibility_modifier' and 'static' in self.text(c))
            for c in node.children
        )
        # Better static detection: look for any `static` token sibling.
        for c in node.children:
            if c.type == 'static_modifier':
                is_static = True
        params: list[str] = []
        if is_method and not is_static:
            params.append('self')
        if params_node is not None:
            for p in params_node.children:
                if p.type in ('simple_parameter', 'variadic_parameter',
                               'property_promotion_parameter'):
                    pname = ''
                    pdefault: str | None = None
                    got_eq = False
                    for pc in p.children:
                        if pc.type == 'variable_name':
                            pname = self.text(pc).lstrip('$')
                        elif pc.type == '=':
                            got_eq = True
                        elif got_eq and pdefault is None:
                            pdefault = self.visit_expr(pc)
                    if pname:
                        pname = _safe_name(pname)
                        if pdefault is not None:
                            params.append(f'{pname}={pdefault}')
                        else:
                            params.append(pname)
        body_node = node.child_by_field_name('body')
        body_py = self.visit(body_node, indent + 1) if body_node else ''
        if not body_py.strip():
            body_py = '    ' * (indent + 1) + 'pass'
        pad = '    ' * indent
        return f'{pad}def {_safe_name(name)}({", ".join(params)}):\n{body_py}'

    # ── Statements ────────────────────────────────────────────────

    def visit_compound_statement(self, node, indent: int) -> str:
        out: list[str] = []
        for c in node.children:
            if c.type in ('{', '}', 'comment'):
                continue
            piece = self.visit(c, indent)
            if piece.strip():
                out.append(piece)
        if not out:
            return '    ' * indent + 'pass'
        return '\n'.join(out)

    def visit_expression_statement(self, node, indent: int) -> str:
        # Children: <expr> ;
        for c in node.children:
            if c.type != ';':
                return '    ' * indent + self.visit_expr(c)
        return ''

    def visit_echo_statement(self, node, indent: int) -> str:
        args = []
        for c in node.children:
            if c.type not in ('echo', ';', ','):
                args.append(self.visit_expr(c))
        return '    ' * indent + f'print({", ".join(args)})'

    def visit_return_statement(self, node, indent: int) -> str:
        for c in node.children:
            if c.type not in ('return', ';'):
                return '    ' * indent + 'return ' + self.visit_expr(c)
        return '    ' * indent + 'return'

    def visit_throw_statement(self, node, indent: int) -> str:
        for c in node.children:
            if c.type not in ('throw', ';'):
                return '    ' * indent + 'raise ' + self.visit_expr(c)
        return '    ' * indent + 'raise'

    def visit_break_statement(self, node, indent: int) -> str:
        return '    ' * indent + 'break'

    def visit_continue_statement(self, node, indent: int) -> str:
        return '    ' * indent + 'continue'

    def visit_unset_statement(self, node, indent: int) -> str:
        # `unset($x, $y)` — Python's nearest analogue is `del x; del y`.
        targets = []
        for c in node.children:
            if c.type not in ('unset', '(', ')', ',', ';'):
                targets.append(self.visit_expr(c))
        if not targets:
            return ''
        pad = '    ' * indent
        return '\n'.join(f'{pad}{t} = None  # PHP unset()' for t in targets)

    def visit_exit_statement(self, node, indent: int) -> str:
        # `exit;`, `exit(1);`, `die("msg");`
        for c in node.children:
            if c.type == 'parenthesized_expression':
                # extract inner
                for cc in c.children:
                    if cc.type not in ('(', ')'):
                        return '    ' * indent + f'sys.exit({self.visit_expr(cc)})'
                return '    ' * indent + 'sys.exit()'
        return '    ' * indent + 'sys.exit()'

    def visit_empty_statement(self, node, indent: int) -> str:
        # Bare `;` — no-op in Python (we just emit nothing).
        return ''

    def visit_global_declaration(self, node, indent: int) -> str:
        # `global $foo, $bar;` → `global foo, bar`
        names = []
        for c in node.children:
            if c.type == 'variable_name':
                names.append(_safe_name(self.text(c).lstrip('$')))
        if not names:
            return ''
        return '    ' * indent + f'global {", ".join(names)}'

    def visit_function_static_declaration(self, node, indent: int) -> str:
        # `static $foo = 0;` inside a function — Python has no
        # function-scoped statics. Emit a porter marker plus a
        # nonlocal-style hint so the file still compiles.
        for c in node.children:
            if c.type == 'static_variable_declaration':
                name = ''
                default = 'None'
                got_eq = False
                for cc in c.children:
                    if cc.type == 'variable_name':
                        name = self.text(cc).lstrip('$')
                    elif cc.type == '=':
                        got_eq = True
                    elif got_eq:
                        default = self.visit_expr(cc)
                if name:
                    pad = '    ' * indent
                    return (f'{pad}{_safe_name(name)} = {default}'
                            f'  # PORTER: PHP static — promote to '
                            f'class attr or default-arg trick')
        return ''

    def visit_text_interpolation(self, node, indent: int) -> str:
        # Inline HTML/text between `?>...<?php`. Emit a porter marker
        # with the original snippet so the porter sees it.
        snippet = self.text(node).strip()[:80].replace('\n', ' ')
        if not snippet:
            return ''
        return '    ' * indent + f'# PORTER: inline HTML/text: {snippet!r}'

    def visit_use_declaration(self, node, indent: int) -> str:
        # `use TraitName;` inside a class. Python uses multiple
        # inheritance instead of traits. Porter marker.
        return '    ' * indent + f'# PORTER: trait use — {self.text(node)}'

    def visit_named_label_statement(self, node, indent: int) -> str:
        return '    ' * indent + f'# PORTER: PHP label — {self.text(node)}'

    def visit_goto_statement(self, node, indent: int) -> str:
        return '    ' * indent + f'# PORTER: PHP goto — {self.text(node)}'

    def visit_declare_statement(self, node, indent: int) -> str:
        # `declare(strict_types=1);` — Python is always strict-typed
        # in the way PHP means here; no-op.
        return ''

    def visit_if_statement(self, node, indent: int) -> str:
        cond_node = node.child_by_field_name('condition')
        body_node = node.child_by_field_name('body')
        cond = self.visit_expr(cond_node) if cond_node else 'True'
        # Strip outer parens (PHP `if ($x)` always has them).
        if cond.startswith('(') and cond.endswith(')'):
            cond = cond[1:-1].strip()
        # PHP allows assignment-in-condition (`if ($x = expr())`).
        # Convert to Python's walrus operator `:=` so the file
        # compiles AND captures the binding.
        cond = self._maybe_walrus(cond)
        body_py = self.visit(body_node, indent + 1) if body_node else \
                   '    ' * (indent + 1) + 'pass'
        pad = '    ' * indent
        out = f'{pad}if {cond}:\n{body_py}'
        # else_clause / else_if_clause children
        for c in node.children:
            if c.type == 'else_if_clause':
                ec = c.child_by_field_name('condition')
                eb = c.child_by_field_name('body')
                econd = self.visit_expr(ec) if ec else 'True'
                if econd.startswith('(') and econd.endswith(')'):
                    econd = econd[1:-1].strip()
                ebody = self.visit(eb, indent + 1) if eb else \
                         '    ' * (indent + 1) + 'pass'
                econd = self._maybe_walrus(econd)
                out += f'\n{pad}elif {econd}:\n{ebody}'
            elif c.type == 'else_clause':
                eb = c.child_by_field_name('body')
                if eb is None:
                    # Find a body child manually.
                    for cc in c.children:
                        if cc.type != 'else':
                            eb = cc
                            break
                ebody = self.visit(eb, indent + 1) if eb else \
                         '    ' * (indent + 1) + 'pass'
                out += f'\n{pad}else:\n{ebody}'
        return out

    def visit_while_statement(self, node, indent: int) -> str:
        cond_node = node.child_by_field_name('condition')
        body_node = node.child_by_field_name('body')
        cond = self.visit_expr(cond_node) if cond_node else 'True'
        if cond.startswith('(') and cond.endswith(')'):
            cond = cond[1:-1].strip()
        cond = self._maybe_walrus(cond)
        body_py = self.visit(body_node, indent + 1) if body_node else \
                   '    ' * (indent + 1) + 'pass'
        return f'{"    " * indent}while {cond}:\n{body_py}'

    def _maybe_walrus(self, cond: str) -> str:
        """Convert `var = expr` (PHP assignment-in-condition) into
        Python walrus form `(var := expr)`. Recognises three shapes:
        bare `var = expr`, `(var = expr) <op> rhs`, and a leading
        `not var = expr`."""
        s = cond.strip()
        if ':=' in s or '==' in s.replace('===', '') or '!=' in s.replace('!==', ''):
            return cond
        m = re.match(r'^\(?\s*(?:not\s+)?(\w+)\s*=\s*(?!=)(.+?)\)?$', s)
        if m and '=' not in m.group(2):
            prefix = 'not ' if s.lstrip('(').strip().startswith('not ') else ''
            return f'{prefix}({m.group(1)} := {m.group(2).strip()})'
        return cond

    def visit_do_statement(self, node, indent: int) -> str:
        # PHP `do { } while (cond);` → `while True: ... if not cond: break`
        body_node = node.child_by_field_name('body')
        cond_node = node.child_by_field_name('condition')
        body_py = self.visit(body_node, indent + 1) if body_node else \
                   '    ' * (indent + 1) + 'pass'
        cond = self.visit_expr(cond_node) if cond_node else 'True'
        if cond.startswith('(') and cond.endswith(')'):
            cond = cond[1:-1].strip()
        pad = '    ' * indent
        return (f'{pad}while True:\n{body_py}\n'
                f'{pad}    if not ({cond}): break')

    def visit_for_statement(self, node, indent: int) -> str:
        # Try to recognise `for ($i = N; $i < M; $i++)` → `for i in range(...)`.
        kids = list(node.children)
        # Field names: initialize, condition, update, body
        init = node.child_by_field_name('initialize')
        cond = node.child_by_field_name('condition')
        upd = node.child_by_field_name('update')
        body = node.child_by_field_name('body')
        m_init = re.match(r'^\$(\w+)\s*=\s*(\S+)$',
                           self.text(init).strip() if init else '')
        m_cond = re.match(r'^\$(\w+)\s*<\s*(.+)$',
                           self.text(cond).strip() if cond else '')
        m_upd = re.match(r'^\$(\w+)\+\+$',
                          self.text(upd).strip() if upd else '')
        body_py = self.visit(body, indent + 1) if body else \
                   '    ' * (indent + 1) + 'pass'
        if m_init and m_cond and m_upd \
                and m_init.group(1) == m_cond.group(1) == m_upd.group(1):
            var = _safe_name(m_init.group(1))
            return (f'{"    " * indent}for {var} in range({m_init.group(2)}, '
                    f'{m_cond.group(2)}):\n{body_py}')
        # Fallback: emit a porter marker plus the body.
        pad = '    ' * indent
        return f'{pad}# PORTER: for-loop — rewrite as Python iteration\n{body_py}'

    def visit_foreach_statement(self, node, indent: int) -> str:
        # children include the collection expr, `as`, key/value bindings, body
        body = node.child_by_field_name('body')
        # Walk children to find the collection and bindings.
        coll = None
        key = None
        value = None
        seen_as = False
        for c in node.children:
            if c.type == 'as':
                seen_as = True
                continue
            if c.type in ('foreach', '(', ')'):
                continue
            if c.type == body.type:
                continue
            if not seen_as:
                # First pre-`as` expression is the collection
                if coll is None and c.type not in ('comment',):
                    coll = c
            else:
                # Post-`as` children: variable_name [, =>, variable_name]
                if c.type == 'variable_name':
                    if key is None:
                        key = c
                    else:
                        value = c
                elif c.type == 'pair':
                    # `$k => $v` — represented as a `pair` node sometimes
                    for pc in c.children:
                        if pc.type == 'variable_name':
                            if key is None:
                                key = pc
                            else:
                                value = pc
        if coll is None:
            return self.unknown(node, indent)
        coll_py = self.visit_expr(coll)
        body_py = self.visit(body, indent + 1) if body else \
                   '    ' * (indent + 1) + 'pass'
        pad = '    ' * indent
        if key is not None and value is not None:
            kn = _safe_name(self.text(key).lstrip('$'))
            vn = _safe_name(self.text(value).lstrip('$'))
            return f'{pad}for {kn}, {vn} in {coll_py}.items():\n{body_py}'
        if key is not None:
            vn = _safe_name(self.text(key).lstrip('$'))
            return f'{pad}for {vn} in {coll_py}:\n{body_py}'
        return self.unknown(node, indent)

    def visit_switch_statement(self, node, indent: int) -> str:
        cond_node = node.child_by_field_name('condition')
        body_node = node.child_by_field_name('body')
        subject = self.visit_expr(cond_node) if cond_node else 'None'
        if subject.startswith('(') and subject.endswith(')'):
            subject = subject[1:-1].strip()
        pad = '    ' * indent
        out = [f'{pad}match {subject}:']
        if body_node is not None:
            current_label = None
            current_body: list[str] = []
            for c in body_node.children:
                if c.type == 'case_statement':
                    if current_label is not None:
                        out.append(self._render_case(current_label,
                                                       current_body, indent))
                    # Find `case <expr>:`
                    val = None
                    for cc in c.children:
                        if cc.type not in ('case', ':'):
                            val = cc
                            break
                    current_label = self.visit_expr(val) if val else 'None'
                    current_body = []
                    # The case_statement may also contain inline body
                    # statements after the `:`; collect them.
                    after_colon = False
                    for cc in c.children:
                        if cc.type == ':':
                            after_colon = True
                            continue
                        if after_colon and cc.type not in ('break_statement',):
                            current_body.append(self.visit(cc, indent + 2))
                elif c.type == 'default_statement':
                    if current_label is not None:
                        out.append(self._render_case(current_label,
                                                       current_body, indent))
                    current_label = '_'
                    current_body = []
                    after_colon = False
                    for cc in c.children:
                        if cc.type == ':':
                            after_colon = True
                            continue
                        if after_colon and cc.type not in ('break_statement',):
                            current_body.append(self.visit(cc, indent + 2))
            if current_label is not None:
                out.append(self._render_case(current_label, current_body, indent))
        return '\n'.join(out)

    def _render_case(self, label: str, body: list[str], indent: int) -> str:
        pad = '    ' * indent
        body_py = '\n'.join(b for b in body if b.strip()) or \
                   pad + '        pass'
        return f'{pad}    case {label}:\n{body_py}'

    def visit_try_statement(self, node, indent: int) -> str:
        # Walk children: `try { body } catch (Type $e) { body } finally { body }`
        out: list[str] = []
        pad = '    ' * indent
        body = None
        catches: list = []
        finally_block = None
        for c in node.children:
            if c.type == 'compound_statement' and body is None:
                body = c
            elif c.type == 'catch_clause':
                catches.append(c)
            elif c.type == 'finally_clause':
                finally_block = c
        body_py = self.visit(body, indent + 1) if body else \
                   pad + '    pass'
        out.append(f'{pad}try:\n{body_py}')
        for cc in catches:
            ex_type = 'Exception'
            ex_var = None
            cc_body = None
            for ccc in cc.children:
                if ccc.type == 'type_list':
                    types = [self.text(t).replace('\\', '.').lstrip('.')
                             for t in ccc.children if t.type in
                             ('name', 'qualified_name')]
                    if types:
                        ex_type = types[0] if len(types) == 1 \
                                  else f'({", ".join(types)})'
                elif ccc.type in ('name', 'qualified_name'):
                    ex_type = self.text(ccc).replace('\\', '.').lstrip('.')
                elif ccc.type == 'variable_name':
                    ex_var = self.text(ccc).lstrip('$')
                elif ccc.type == 'compound_statement':
                    cc_body = ccc
            cc_body_py = self.visit(cc_body, indent + 1) if cc_body else \
                          pad + '    pass'
            ex_clause = (f'except {ex_type} as {_safe_name(ex_var)}'
                         if ex_var else f'except {ex_type}')
            out.append(f'{pad}{ex_clause}:\n{cc_body_py}')
        if finally_block is not None:
            f_body = None
            for fc in finally_block.children:
                if fc.type == 'compound_statement':
                    f_body = fc
            f_body_py = self.visit(f_body, indent + 1) if f_body else \
                         pad + '    pass'
            out.append(f'{pad}finally:\n{f_body_py}')
        return '\n'.join(out)

    # ── Expressions ───────────────────────────────────────────────

    def visit_expr(self, node) -> str:
        """Translate an expression node to a Python expression string."""
        t = node.type
        method = getattr(self, f'expr_{t}', None)
        if method is not None:
            return method(node)
        # Fallback: best-effort using the source text + light cleanup.
        return self._fallback_expr(node)

    def _fallback_expr(self, node) -> str:
        s = self.text(node)
        # Light catch-all rewrites for nodes we don't have visitors for.
        s = s.replace('$this->', 'self.')
        s = s.replace('->', '.')
        s = re.sub(r'\$(\w+)', r'\1', s)
        return s

    def expr_variable_name(self, node) -> str:
        return _safe_name(self.text(node).lstrip('$'))

    def expr_name(self, node) -> str:
        return _safe_name(self.text(node))

    def expr_qualified_name(self, node) -> str:
        return _safe_name(self.text(node).replace('\\', '.').lstrip('.'))

    def expr_integer(self, node) -> str:
        return self.text(node)

    def expr_float(self, node) -> str:
        return self.text(node)

    def expr_boolean(self, node) -> str:
        return self.text(node).capitalize()

    def expr_null(self, node) -> str:
        return 'None'

    def expr_string(self, node) -> str:
        return self._render_string(node)

    def expr_encapsed_string(self, node) -> str:
        # Double-quoted PHP string with `$var` interpolation. Convert
        # to a Python f-string by walking the children: literal pieces
        # stay raw, `variable_name` children become `{var}`. Falls
        # back to raw text if the structure is unfamiliar.
        try:
            parts = []
            has_interpolation = False
            for c in node.children:
                if c.type in ('"', "'"):
                    continue
                if c.type == 'variable_name':
                    parts.append('{' + _safe_name(self.text(c).lstrip('$')) + '}')
                    has_interpolation = True
                elif c.type == 'string_value':
                    parts.append(self.text(c))
                else:
                    return self._render_string(node)
            body = ''.join(parts)
            return ('f"' + body.replace('"', '\\"') + '"'
                    if has_interpolation else
                    '"' + body.replace('"', '\\"') + '"')
        except Exception:
            return self._render_string(node)

    def expr_string_literal(self, node) -> str:
        return self._render_string(node)

    def _render_string(self, node) -> str:
        """Emit a Python string literal that mirrors a PHP string.

        PHP single- and double-quoted strings can contain literal
        newlines; Python single-line quotes can't. Multi-line strings
        get triple-quoted form. Strings carrying `\\u`/`\\x` escape
        sequences in single quotes get a leading `r` prefix (PHP
        doesn't interpret those; Python would and crash on truncated
        forms)."""
        text = self.text(node)
        if '\n' in text and len(text) >= 2:
            quote = text[0]
            if quote in ('"', "'"):
                inner = text[1:-1] if text.endswith(quote) else text[1:]
                inner = inner.replace("'''", r"\'\'\'")
                return "'''" + inner + "'''"
        if text.startswith("'") and ('\\u' in text or '\\x' in text):
            return 'r' + text
        return text

    def expr_binary_expression(self, node) -> str:
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')
        op_node = node.child_by_field_name('operator')
        op = self.text(op_node) if op_node else ''
        l = self.visit_expr(left) if left else ''
        r = self.visit_expr(right) if right else ''
        op_map = {'.': '+', '===': '==', '!==': '!=', '&&': 'and',
                   '||': 'or', '??': 'or'}
        py_op = op_map.get(op, op)
        return f'({l} {py_op} {r})'

    def expr_unary_op_expression(self, node) -> str:
        op_node = node.child_by_field_name('operator')
        op = self.text(op_node) if op_node else ''
        operand = node.child_by_field_name('argument') or node.child_by_field_name('operand')
        if operand is None:
            for c in node.children:
                if c is not op_node:
                    operand = c; break
        e = self.visit_expr(operand) if operand else ''
        if op == '!':
            return f'(not {e})'
        return f'({op}{e})'

    def expr_assignment_expression(self, node) -> str:
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')
        # PHP `$arr[] = $x` (array push) → `arr.append(x)`. Detect
        # an empty-index subscript on the LHS.
        if left is not None and left.type == 'subscript_expression':
            has_index = any(c.type not in ('[', ']') and
                             c is not left.child(0) for c in left.children)
            # Above is fragile; simpler check: 3 children means `arr [ ]`
            # (no index), 4 children means `arr [ idx ]`.
            non_brackets = [c for c in left.children
                            if c.type not in ('[', ']')]
            if len(non_brackets) == 1:
                # No index — it's an array-push.
                target_node = non_brackets[0]
                target = self.visit_expr(target_node)
                value = self.visit_expr(right) if right else ''
                return f'{target}.append({value})'
        l = self.visit_expr(left) if left else ''
        r = self.visit_expr(right) if right else ''
        return f'{l} = {r}'

    def expr_augmented_assignment_expression(self, node) -> str:
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')
        op_node = node.child_by_field_name('operator')
        op = self.text(op_node) if op_node else '='
        # PHP `.=` (string concat assign) → Python `+=`
        if op == '.=':
            op = '+='
        l = self.visit_expr(left) if left else ''
        r = self.visit_expr(right) if right else ''
        return f'{l} {op} {r}'

    def expr_conditional_expression(self, node) -> str:
        # `cond ? then : else`. tree-sitter-php gives us field names.
        cond = node.child_by_field_name('condition')
        then = node.child_by_field_name('body')
        alt = node.child_by_field_name('alternative')
        c = self.visit_expr(cond) if cond else ''
        if then is None:
            # PHP Elvis operator `cond ?: alt` — `cond` itself is the value.
            t = c
        else:
            t = self.visit_expr(then)
        a = self.visit_expr(alt) if alt else ''
        return f'({t} if {c} else {a})'

    def expr_member_access_expression(self, node) -> str:
        obj = node.child_by_field_name('object')
        name = node.child_by_field_name('name')
        o = self.visit_expr(obj) if obj else ''
        n = _safe_name(self.text(name).lstrip('$')) if name else ''
        # `$this->x` → `self.x`
        if o == 'this':
            o = 'self'
        return f'{o}.{n}'

    def expr_nullsafe_member_access_expression(self, node) -> str:
        # `$x?->y` — semantics differ; emit `(o.n if o is not None else None)`.
        obj = node.child_by_field_name('object')
        name = node.child_by_field_name('name')
        o = self.visit_expr(obj) if obj else ''
        n = _safe_name(self.text(name).lstrip('$')) if name else ''
        if o == 'this':
            o = 'self'
        return f'({o}.{n} if {o} is not None else None)'

    def expr_member_call_expression(self, node) -> str:
        obj = node.child_by_field_name('object')
        name = node.child_by_field_name('name')
        args = node.child_by_field_name('arguments')
        o = self.visit_expr(obj) if obj else ''
        if o == 'this':
            o = 'self'
        n = _safe_name(self.text(name).lstrip('$')) if name else ''
        a = self._render_arguments(args)
        return f'{o}.{n}({a})'

    def expr_nullsafe_member_call_expression(self, node) -> str:
        obj = node.child_by_field_name('object')
        name = node.child_by_field_name('name')
        args = node.child_by_field_name('arguments')
        o = self.visit_expr(obj) if obj else ''
        if o == 'this':
            o = 'self'
        n = _safe_name(self.text(name).lstrip('$')) if name else ''
        a = self._render_arguments(args)
        return f'({o}.{n}({a}) if {o} is not None else None)'

    def _scoped_parts(self, node):
        """Pull out the scope, name, and arguments from any
        scoped-access node. tree-sitter-php often doesn't tag these
        children with field names, so we iterate by position."""
        scope_node = None
        name_node = None
        args_node = None
        for c in node.children:
            if c.type == '::':
                continue
            if c.type == 'arguments':
                args_node = c
            elif scope_node is None:
                scope_node = c
            elif name_node is None:
                name_node = c
        return scope_node, name_node, args_node

    def expr_scoped_call_expression(self, node) -> str:
        # `Foo::bar(...)` → `Foo.bar(...)`
        scope_node, name_node, args_node = self._scoped_parts(node)
        s = self.text(scope_node).replace('\\', '.').lstrip('.') \
            if scope_node else ''
        if s == 'static':
            s = 'cls'
        if s == 'parent':
            return (f'super().{_safe_name(self.text(name_node).lstrip("$"))}('
                    f'{self._render_arguments(args_node)})')
        n = _safe_name(self.text(name_node).lstrip('$')) if name_node else ''
        a = self._render_arguments(args_node)
        return f'{s}.{n}({a})'

    def expr_scoped_property_access_expression(self, node) -> str:
        # `Foo::$bar` → `Foo.bar`
        scope_node, name_node, _ = self._scoped_parts(node)
        s = self.text(scope_node).replace('\\', '.').lstrip('.') \
            if scope_node else ''
        n = _safe_name(self.text(name_node).lstrip('$')) if name_node else ''
        return f'{s}.{n}'

    def expr_class_constant_access_expression(self, node) -> str:
        # `Foo::CONST` / `Foo::class` / `self::CONST` / `static::class`.
        # Children are positional in tree-sitter-php: [scope, ::, name].
        scope_node = None
        name_node = None
        for c in node.children:
            if c.type == '::':
                continue
            if scope_node is None:
                scope_node = c
            else:
                name_node = c
        s = self.text(scope_node).replace('\\', '.').lstrip('.') \
            if scope_node else ''
        if s == 'static':
            s = 'cls'
        if name_node is not None and self.text(name_node) == 'class':
            return s if s != 'self' else self.text(scope_node)
        n = self.text(name_node) if name_node else ''
        return f'{s}.{n}'

    def expr_function_call_expression(self, node) -> str:
        fn_node = node.child_by_field_name('function')
        args = node.child_by_field_name('arguments')
        fn_name = self.text(fn_node) if fn_node else ''
        a_list = self._argument_list(args)
        # Stdlib mapping
        if fn_name in _PHP_TO_PY:
            mapping = _PHP_TO_PY[fn_name]
            if isinstance(mapping, str):
                return f'{mapping}({", ".join(a_list)})'
            try:
                result = mapping(a_list)
            except Exception:
                result = None
            if result is not None:
                return result
        return f'{fn_name}({", ".join(a_list)})'

    def expr_object_creation_expression(self, node) -> str:
        # `new Foo(...)` → `Foo(...)`
        type_node = None
        args_node = None
        for c in node.children:
            if c.type in ('name', 'qualified_name'):
                type_node = c
            elif c.type == 'arguments':
                args_node = c
        cls = self.text(type_node).replace('\\', '.').lstrip('.') \
              if type_node else 'object'
        a = self._render_arguments(args_node)
        return f'{cls}({a})'

    def expr_subscript_expression(self, node) -> str:
        obj = node.child_by_field_name('dereferencable_expression') or \
              node.child(0)
        idx = node.child_by_field_name('index') or node.child(2)
        o = self.visit_expr(obj) if obj else ''
        i = self.visit_expr(idx) if idx else ''
        return f'{o}[{i}]'

    def expr_array_creation_expression(self, node) -> str:
        return self._render_array(node)

    def expr_array_creation(self, node) -> str:
        return self._render_array(node)

    def _render_array(self, node) -> str:
        """Translate a PHP array literal `[k => v, ...]` to a Python
        dict, list, or list-with-tuples (mixed) depending on the
        contents. Walks `array_element_initializer` children."""
        elements: list[tuple[str | None, str]] = []
        for c in node.children:
            if c.type == 'array_element_initializer':
                key = None
                value = None
                seen_arrow = False
                for cc in c.children:
                    if cc.type == '=>':
                        seen_arrow = True
                        continue
                    if cc.type == ',':
                        continue
                    if not seen_arrow:
                        if key is None:
                            # If no `=>` follows, this is a positional value.
                            key = self.visit_expr(cc)
                    else:
                        value = self.visit_expr(cc)
                if value is None:
                    elements.append((None, key or ''))
                else:
                    elements.append((key, value))
        has_keys = any(k is not None for k, _ in elements)
        has_pos = any(k is None for k, _ in elements)
        if has_keys and not has_pos:
            return '{' + ', '.join(f'{k}: {v}' for k, v in elements) + '}'
        if has_keys and has_pos:
            # Mixed — emit as list of tuples for keyed entries.
            parts = []
            for k, v in elements:
                if k is None:
                    parts.append(v)
                else:
                    parts.append(f'({k}, {v})')
            return '[' + ', '.join(parts) + ']'
        return '[' + ', '.join(v for _, v in elements) + ']'

    def expr_parenthesized_expression(self, node) -> str:
        for c in node.children:
            if c.type not in ('(', ')'):
                return f'({self.visit_expr(c)})'
        return '()'

    def expr_cast_expression(self, node) -> str:
        # `(int) $x` etc.
        kind = ''
        target = None
        for c in node.children:
            if c.type == 'cast_type':
                kind = self.text(c).lower()
            elif c.type not in ('(', ')'):
                target = c
        if not kind or target is None:
            return self.text(node)
        py_type = _CAST_TYPE.get(kind, kind)
        return f'{py_type}({self.visit_expr(target)})'

    def expr_update_expression(self, node) -> str:
        # `$x++`, `++$x`, `$x--`, `--$x`. Python has no equivalent;
        # rewrite the postfix forms as compound assignment when used
        # as a statement-level expression.
        text = self.text(node)
        if text.endswith('++'):
            inner = text[:-2]
            inner_clean = re.sub(r'\$', '', inner).replace('->', '.')
            return f'{inner_clean} += 1'
        if text.endswith('--'):
            inner = text[:-2]
            inner_clean = re.sub(r'\$', '', inner).replace('->', '.')
            return f'{inner_clean} -= 1'
        if text.startswith('++'):
            inner = text[2:]
            inner_clean = re.sub(r'\$', '', inner).replace('->', '.')
            return f'{inner_clean} += 1'
        if text.startswith('--'):
            inner = text[2:]
            inner_clean = re.sub(r'\$', '', inner).replace('->', '.')
            return f'{inner_clean} -= 1'
        return text

    def expr_print_intrinsic(self, node) -> str:
        # `print expr` (PHP language construct)
        for c in node.children:
            if c.type != 'print':
                return f'print({self.visit_expr(c)})'
        return 'print()'

    def expr_include_expression(self, node) -> str:
        return f'# PORTER: {self.text(node)} — translate to Python import'

    def expr_require_expression(self, node) -> str:
        return f'# PORTER: {self.text(node)} — translate to Python import'

    def expr_throw_expression(self, node) -> str:
        for c in node.children:
            if c.type != 'throw':
                return f'(_ for _ in ()).throw({self.visit_expr(c)})'
        return 'raise RuntimeError()'

    def expr_yield_expression(self, node) -> str:
        for c in node.children:
            if c.type not in ('yield', 'from'):
                return f'(yield {self.visit_expr(c)})'
        return '(yield)'

    def expr_clone_expression(self, node) -> str:
        for c in node.children:
            if c.type != 'clone':
                return f'__import__("copy").copy({self.visit_expr(c)})'
        return 'None'

    def expr_anonymous_function(self, node) -> str:
        # PHP closures `function ($a, $b) use ($c) { ... }`. Python
        # `lambda` is single-expression; PHP closures hold full
        # bodies. Emit a porter marker with the original.
        self.porter_count += 1
        return (f'(lambda *args, **kwargs: '
                f'__import__("warnings").warn("PORTER: PHP closure"))'
                f'  # PORTER closure: {self.text(node)[:80]}')

    def expr_arrow_function(self, node) -> str:
        # PHP 7.4 `fn ($x) => $x * 2` — single-expression closure,
        # maps cleanly to Python lambda.
        params_node = node.child_by_field_name('parameters')
        body_node = node.child_by_field_name('body')
        params = []
        if params_node is not None:
            for p in params_node.children:
                if p.type == 'simple_parameter':
                    for pc in p.children:
                        if pc.type == 'variable_name':
                            params.append(_safe_name(self.text(pc).lstrip('$')))
        body = self.visit_expr(body_node) if body_node else 'None'
        return f'lambda {", ".join(params)}: {body}'

    def _render_arguments(self, args_node) -> str:
        return ', '.join(self._argument_list(args_node))

    def _argument_list(self, args_node) -> list[str]:
        if args_node is None:
            return []
        out: list[str] = []
        for c in args_node.children:
            if c.type == 'argument':
                # Look for named arg (PHP 8): `name: $value`
                name_node = c.child_by_field_name('name')
                # `argument` may have a `name` field; otherwise the
                # whole node is just the expression.
                if name_node is not None:
                    val_text = self._argument_value(c)
                    out.append(f'{self.text(name_node)}={val_text}')
                else:
                    out.append(self._argument_value(c))
            elif c.type not in ('(', ')', ','):
                # Older grammars: arguments listed directly as exprs
                out.append(self.visit_expr(c))
        return out

    def _argument_value(self, arg_node) -> str:
        """Pull the value expression out of an `argument` node."""
        for c in arg_node.children:
            if c.type not in ('name', ':', ','):
                return self.visit_expr(c)
        return self.text(arg_node)

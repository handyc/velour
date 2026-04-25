"""Translate arbitrary PHP source into Python.

This is the catch-all that complements every framework-specific
lifter. Where liftlaravel / liftsymfony / liftcakephp / liftyii /
liftcodeigniter understand the *idioms* of their respective
frameworks, this module understands PHP itself: assignments,
control flow, classes, functions, expressions, the standard
library, and the punctuation differences (`->` vs `.`, `::` vs
`.`, `=>` vs `:`, `.` for concat vs `+`, `$var` vs `var`).

The output is "Python-shaped" PHP — ready for the porter to clean
up rather than ready for production. Anything that can't be
translated (eval, complex regex, runtime metaprogramming, custom
operators) emits a `# PORTER:` marker with the original PHP line
preserved underneath.

Pure Python, no LLM, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from datalift._php import strip_php_comments


# ── Records ────────────────────────────────────────────────────────

@dataclass
class PhpFunction:
    name: str
    args: list[str]            # `['name', 'count=10']` parameter list
    body_python: str           # Translated body
    body_php: str              # Original PHP body
    return_type: str = ''      # e.g. 'string', '?int' (informational)


@dataclass
class PhpProperty:
    name: str
    visibility: str            # 'public' / 'protected' / 'private'
    type_hint: str = ''
    default: str = ''


@dataclass
class PhpClass:
    name: str
    parent: str = ''
    interfaces: list[str] = field(default_factory=list)
    properties: list[PhpProperty] = field(default_factory=list)
    methods: list[PhpFunction] = field(default_factory=list)
    constants: list[tuple[str, str]] = field(default_factory=list)
    is_abstract: bool = False
    is_final: bool = False


@dataclass
class PhpFile:
    source: Path
    namespace: str = ''
    uses: list[str] = field(default_factory=list)
    functions: list[PhpFunction] = field(default_factory=list)
    classes: list[PhpClass] = field(default_factory=list)
    top_level_python: str = ''
    porter_markers: int = 0


@dataclass
class PhpCodeLiftResult:
    files: list[PhpFile] = field(default_factory=list)
    skipped_files: list[Path] = field(default_factory=list)


# ── PHP standard-library function map ─────────────────────────────
#
# Translating function calls is one of the highest-value moves: it
# cleans up most lines and makes the output recognisably Python.
# The map is intentionally exhaustive for the common 80% — the rest
# emit a porter marker.

_PHP_TO_PYTHON_FUNCS: dict[str, str] = {
    # String functions
    'strlen':           'len',
    'count':            'len',
    'sizeof':           'len',
    'str_repeat':       lambda args: f'({args[0]} * {args[1]})' if len(args) == 2 else None,
    'strtolower':       lambda args: f'{args[0]}.lower()' if args else None,
    'strtoupper':       lambda args: f'{args[0]}.upper()' if args else None,
    'ucfirst':          lambda args: f'{args[0]}.capitalize()' if args else None,
    'ucwords':          lambda args: f'{args[0]}.title()' if args else None,
    'trim':             lambda args: f'{args[0]}.strip()' if len(args) == 1 else f'{args[0]}.strip({args[1]})',
    'ltrim':            lambda args: f'{args[0]}.lstrip()' if len(args) == 1 else f'{args[0]}.lstrip({args[1]})',
    'rtrim':            lambda args: f'{args[0]}.rstrip()' if len(args) == 1 else f'{args[0]}.rstrip({args[1]})',
    'str_replace':      lambda args: f'{args[2]}.replace({args[0]}, {args[1]})' if len(args) == 3 else None,
    'str_contains':     lambda args: f'({args[1]} in {args[0]})' if len(args) == 2 else None,
    'str_starts_with':  lambda args: f'{args[0]}.startswith({args[1]})' if len(args) == 2 else None,
    'str_ends_with':    lambda args: f'{args[0]}.endswith({args[1]})' if len(args) == 2 else None,
    'strpos':           lambda args: f'{args[0]}.find({args[1]})' if len(args) >= 2 else None,
    'substr':           lambda args: f'{args[0]}[{args[1]}:{args[1]}+{args[2]}]' if len(args) == 3 else f'{args[0]}[{args[1]}:]',
    'explode':          lambda args: f'{args[1]}.split({args[0]})' if len(args) == 2 else None,
    'implode':          lambda args: f'{args[0]}.join({args[1]})' if len(args) == 2 else f"''.join({args[0]})",
    'join':             lambda args: f'{args[0]}.join({args[1]})' if len(args) == 2 else f"''.join({args[0]})",
    'sprintf':          lambda args: f'({args[0]} % ({", ".join(args[1:])}))' if len(args) >= 2 else args[0],
    'printf':           lambda args: f'print({args[0]} % ({", ".join(args[1:])}))' if len(args) >= 2 else f'print({args[0]})',
    'nl2br':            lambda args: f"{args[0]}.replace('\\n', '<br>\\n')" if args else None,
    'htmlspecialchars': lambda args: f'html.escape({args[0]})' if args else None,
    'htmlentities':     lambda args: f'html.escape({args[0]})' if args else None,
    'urlencode':        lambda args: f'urllib.parse.quote({args[0]})' if args else None,
    'urldecode':        lambda args: f'urllib.parse.unquote({args[0]})' if args else None,
    'json_encode':      lambda args: f'json.dumps({args[0]})' if args else None,
    'json_decode':      lambda args: f'json.loads({args[0]})' if len(args) == 1 else f'json.loads({args[0]})',
    'md5':              lambda args: f'hashlib.md5({args[0]}.encode()).hexdigest()' if args else None,
    'sha1':             lambda args: f'hashlib.sha1({args[0]}.encode()).hexdigest()' if args else None,
    'base64_encode':    lambda args: f'base64.b64encode({args[0]}.encode()).decode()' if args else None,
    'base64_decode':    lambda args: f'base64.b64decode({args[0]}).decode()' if args else None,

    # Array functions
    'array_keys':       lambda args: f'list({args[0]}.keys())' if args else None,
    'array_values':     lambda args: f'list({args[0]}.values())' if args else None,
    'array_merge':      lambda args: f'{{**{args[0]}, **{args[1]}}}' if len(args) == 2 else f'({" + ".join(args)})',
    'array_map':        lambda args: f'list(map({args[0]}, {args[1]}))' if len(args) == 2 else None,
    'array_filter':     lambda args: f'list(filter({args[1]}, {args[0]}))' if len(args) == 2 else f'[x for x in {args[0]} if x]',
    'array_reduce':     lambda args: f'functools.reduce({args[1]}, {args[0]}, {args[2]})' if len(args) == 3 else f'functools.reduce({args[1]}, {args[0]})',
    'array_search':     lambda args: f'(list({args[1]}).index({args[0]}) if {args[0]} in {args[1]} else False)' if len(args) >= 2 else None,
    'array_unique':     lambda args: f'list(dict.fromkeys({args[0]}))' if args else None,
    'array_reverse':    lambda args: f'list(reversed({args[0]}))' if args else None,
    'array_slice':      lambda args: f'{args[0]}[{args[1]}:{args[1]}+{args[2]}]' if len(args) == 3 else f'{args[0]}[{args[1]}:]',
    'array_push':       lambda args: f'{args[0]}.append({args[1]})' if len(args) == 2 else None,
    'array_pop':        lambda args: f'{args[0]}.pop()' if args else None,
    'array_shift':      lambda args: f'{args[0]}.pop(0)' if args else None,
    'array_unshift':    lambda args: f'{args[0]}.insert(0, {args[1]})' if len(args) == 2 else None,
    'array_combine':    lambda args: f'dict(zip({args[0]}, {args[1]}))' if len(args) == 2 else None,
    'array_flip':       lambda args: f'{{v: k for k, v in {args[0]}.items()}}' if args else None,
    'array_diff':       lambda args: f'[x for x in {args[0]} if x not in {args[1]}]' if len(args) == 2 else None,
    'array_intersect':  lambda args: f'[x for x in {args[0]} if x in {args[1]}]' if len(args) == 2 else None,
    'in_array':         lambda args: f'({args[0]} in {args[1]})' if len(args) >= 2 else None,
    'array_key_exists': lambda args: f'({args[0]} in {args[1]})' if len(args) == 2 else None,
    'sort':             lambda args: f'{args[0]}.sort()' if args else None,
    'rsort':            lambda args: f'{args[0]}.sort(reverse=True)' if args else None,
    'asort':            lambda args: f'{args[0]} = dict(sorted({args[0]}.items(), key=lambda x: x[1]))' if args else None,
    'ksort':            lambda args: f'{args[0]} = dict(sorted({args[0]}.items()))' if args else None,
    'range':            lambda args: f'list(range({", ".join(args)}))',
    'min':              lambda args: f'min({", ".join(args)})',
    'max':              lambda args: f'max({", ".join(args)})',
    'array_sum':        lambda args: f'sum({args[0]})' if args else None,

    # Math
    'abs':              'abs',
    'floor':            lambda args: f'int({args[0]})' if args else None,
    'ceil':             lambda args: f'(-(-{args[0]} // 1))' if args else None,
    'round':            'round',
    'pow':              lambda args: f'({args[0]} ** {args[1]})' if len(args) == 2 else None,
    'sqrt':             lambda args: f'math.sqrt({args[0]})' if args else None,
    'rand':             lambda args: f'random.randint({args[0]}, {args[1]})' if len(args) == 2 else 'random.randint(0, 2147483647)',
    'mt_rand':          lambda args: f'random.randint({args[0]}, {args[1]})' if len(args) == 2 else 'random.randint(0, 2147483647)',
    'intval':           'int',
    'floatval':         'float',
    'strval':           'str',
    'boolval':          'bool',

    # Type-checks
    'is_array':         lambda args: f'isinstance({args[0]}, list)' if args else None,
    'is_string':        lambda args: f'isinstance({args[0]}, str)' if args else None,
    'is_int':           lambda args: f'isinstance({args[0]}, int)' if args else None,
    'is_integer':       lambda args: f'isinstance({args[0]}, int)' if args else None,
    'is_numeric':       lambda args: f'isinstance({args[0]}, (int, float))' if args else None,
    'is_float':         lambda args: f'isinstance({args[0]}, float)' if args else None,
    'is_bool':          lambda args: f'isinstance({args[0]}, bool)' if args else None,
    'is_null':          lambda args: f'({args[0]} is None)' if args else None,
    'is_object':        lambda args: f'(hasattr({args[0]}, "__dict__"))' if args else None,
    'gettype':          lambda args: f'type({args[0]}).__name__' if args else None,

    # I/O
    'echo':             'print',
    'print':            'print',
    'print_r':          lambda args: f'print({args[0]})' if args else None,
    'var_dump':         lambda args: f'print({args[0]})' if args else None,
    'die':              lambda args: f'sys.exit({args[0]})' if args else 'sys.exit()',
    'exit':             lambda args: f'sys.exit({args[0]})' if args else 'sys.exit()',
    'file_get_contents': lambda args: f'open({args[0]}).read()' if args else None,
    'file_put_contents': lambda args: f'open({args[0]}, "w").write({args[1]})' if len(args) == 2 else None,
    'file_exists':      lambda args: f'os.path.exists({args[0]})' if args else None,
    'is_file':          lambda args: f'os.path.isfile({args[0]})' if args else None,
    'is_dir':           lambda args: f'os.path.isdir({args[0]})' if args else None,
    'mkdir':            lambda args: f'os.makedirs({args[0]}, exist_ok=True)' if args else None,
    'unlink':           lambda args: f'os.remove({args[0]})' if args else None,
    'rename':           lambda args: f'os.rename({args[0]}, {args[1]})' if len(args) == 2 else None,
    'fopen':            lambda args: f'open({args[0]}, {args[1]})' if len(args) == 2 else None,
    'fclose':           lambda args: f'{args[0]}.close()' if args else None,
    'fwrite':           lambda args: f'{args[0]}.write({args[1]})' if len(args) == 2 else None,
    'fread':            lambda args: f'{args[0]}.read({args[1]})' if len(args) == 2 else None,
    'fgets':            lambda args: f'{args[0]}.readline()' if args else None,

    # Date/time
    'time':             lambda args: 'int(time.time())',
    'microtime':        lambda args: 'time.time()',
    'date':             lambda args: f'datetime.datetime.now().strftime({args[0]})' if len(args) == 1 else f'datetime.datetime.fromtimestamp({args[1]}).strftime({args[0]})',
    'strtotime':        lambda args: f'# PORTER: strtotime({args[0]}) — use dateutil.parser.parse',
    'mktime':           lambda args: '# PORTER: mktime → datetime.datetime(...).timestamp()',
    'date_format':      lambda args: f'{args[0]}.strftime({args[1]})' if len(args) == 2 else None,

    # Regex (PCRE)
    'preg_match':       lambda args: f're.search({args[0]}, {args[1]})' if len(args) >= 2 else None,
    'preg_match_all':   lambda args: f're.findall({args[0]}, {args[1]})' if len(args) >= 2 else None,
    'preg_replace':     lambda args: f're.sub({args[0]}, {args[1]}, {args[2]})' if len(args) == 3 else None,
    'preg_split':       lambda args: f're.split({args[0]}, {args[1]})' if len(args) >= 2 else None,
}


# ── Tokeniser-ish helpers ─────────────────────────────────────────

def _balanced_block(src: str, open_idx: int) -> tuple[int, int] | None:
    """Find the closing `}` for the `{` at `open_idx`."""
    depth = 0
    in_str: str | None = None
    i = open_idx
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < len(src):
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch; i += 1; continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return open_idx + 1, i
        i += 1
    return None


def _balanced_paren(src: str, open_idx: int) -> int | None:
    """Find the matching `)` for `(` at `open_idx`."""
    depth = 0
    in_str: str | None = None
    i = open_idx
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < len(src):
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch; i += 1; continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _split_args(s: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str: str | None = None
    for ch in s:
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch; buf.append(ch); continue
        if ch in '([{':
            depth += 1; buf.append(ch)
        elif ch in ')]}':
            depth -= 1; buf.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(buf).strip()); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf).strip())
    return parts


# ── Expression translation ────────────────────────────────────────

def _split_strings(s: str) -> list[tuple[str, bool]]:
    """Split a source string into (chunk, is_string) segments.

    `is_string=True` chunks are PHP string literals (with their
    surrounding quotes) and must be passed through verbatim by every
    expression-rewriting rule."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _STRING_RE.finditer(s):
        if m.start() > pos:
            out.append((s[pos:m.start()], False))
        out.append((m.group('s'), True))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], False))
    return out


def _apply_to_code(s: str, fn) -> str:
    """Apply `fn(chunk)` to every non-string segment in `s` and
    re-stitch the result. String literals pass through unchanged."""
    return ''.join(fn(c) if not is_str else c
                   for c, is_str in _split_strings(s))


def _rewrite_code(chunk: str) -> str:
    """Apply every PHP→Python rewrite rule to a non-string chunk.

    String literals are NEVER passed here — see `_apply_to_code`."""
    s = chunk
    # `$var` → `var`
    s = re.sub(r'\$(\w+)', r'\1', s)

    # `null` / `true` / `false`
    s = re.sub(r'\bnull\b', 'None', s)
    s = re.sub(r'\btrue\b', 'True', s)
    s = re.sub(r'\bfalse\b', 'False', s)

    # Static-style invocations
    s = re.sub(r'\bself::', 'self.', s)
    s = re.sub(r'\bstatic::', 'cls.', s)
    s = re.sub(r'\bparent::', 'super().', s)
    s = re.sub(r'(\w+)::class\b', r'\1', s)
    s = re.sub(r'(\w+)::(\w+)', r'\1.\2', s)

    # `$this->` → `self.`, plus generic `->` → `.`
    s = s.replace('this->', 'self.')
    s = s.replace('->', '.')

    # `array(...)` → `[...]`
    s = re.sub(r'\barray\s*\(', '[', s)

    # `=>` → `:`
    s = s.replace('=>', ':')

    # PHP-strict equality
    s = s.replace('===', '==')
    s = s.replace('!==', '!=')

    # Logical operators
    s = re.sub(r'\s*&&\s*', ' and ', s)
    s = re.sub(r'\s*\|\|\s*', ' or ', s)
    # `!x` → `not x` (not `!=`)
    s = re.sub(r'(?<![!<>=])!(?!=)', 'not ', s)

    # NOTE: string-concat `.` → `+` runs in a separate pass
    # (`_rewrite_string_concat`) since it interacts with the
    # `->` → `.` rewrite — see _translate_expr.

    # `isset(...)` / `empty(...)`
    s = re.sub(r'\bisset\s*\(\s*([^)]+)\s*\)',
                r'(\1 is not None)', s)
    s = re.sub(r'\bempty\s*\(\s*([^)]+)\s*\)',
                r'(not \1)', s)

    # `instanceof` → `isinstance(...)`
    s = re.sub(r'(\w+)\s+instanceof\s+(\w+)',
                r'isinstance(\1, \2)', s)

    # `new Foo(...)` → `Foo(...)`
    s = re.sub(r'\bnew\s+(\w+)', r'\1', s)

    # `??` and `.=`
    s = re.sub(r'\s*\?\?\s*', ' or ', s)
    s = s.replace('.=', '+=')
    return s


def _rewrite_string_concat(expr: str) -> str:
    """Rewrite the PHP string-concat operator `.` to Python `+`.

    `.` is overloaded in PHP-translated source: it is BOTH the
    string-concat operator (`$x . 'foo'`) and — after the
    earlier `->` → `.` rewrite — Python's attribute-access operator
    (`user.name`). To distinguish, require at least one whitespace
    character around the dot. PHP code conventionally writes concat
    with surrounding spaces (`$a . $b`); attribute access never
    has surrounding spaces.
    """
    segments = _split_strings(expr)
    out: list[str] = []
    for i, (chunk, is_str) in enumerate(segments):
        if is_str:
            out.append(chunk)
            continue
        new_chunk = chunk
        # Adjacent to a string literal: the leading/trailing `.`
        # is concat regardless of whitespace.
        if i > 0 and segments[i - 1][1]:
            new_chunk = re.sub(r'^(\s*)\.(\s*)', r'\1+\2', new_chunk)
        if i + 1 < len(segments) and segments[i + 1][1]:
            new_chunk = re.sub(r'(\s*)\.(\s*)$', r'\1+\2', new_chunk)
        # Code-internal: require whitespace on at least one side.
        new_chunk = re.sub(
            r"([\w\)\]])(\s+\.\s*|\s*\.\s+)(?=[\w'\"])",
            r"\1 + ", new_chunk,
        )
        out.append(new_chunk)
    return ''.join(out)


def _translate_expr(expr: str) -> str:
    """Translate a single PHP expression into best-effort Python.

    Most rewriting is routed through `_apply_to_code` so that string
    literals are preserved verbatim — this is what stops `'1.0'`
    from becoming `'1 + 0'` (the concat rule) or `'!'` from becoming
    `'not '` (the logical-not rule). The string-concat operator gets
    a separate string-aware pass because it spans the boundary
    between code and adjacent string literals."""
    if not expr or not expr.strip():
        return expr
    s = _apply_to_code(expr, _rewrite_code)
    s = _rewrite_string_concat(s)
    # Function-call translation runs across string boundaries
    # (call args may be string literals) but only matches function
    # names by `_FUNCALL_RE`, which won't match inside quotes.
    s = _translate_function_calls(s)
    return s


_STRING_RE = re.compile(r"(?P<s>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")")


def _strip_dollars_outside_strings(s: str) -> str:
    """Replace `$var` with `var`, but preserve `$var` inside strings."""
    out: list[str] = []
    pos = 0
    for m in _STRING_RE.finditer(s):
        out.append(re.sub(r'\$(\w+)', r'\1', s[pos:m.start()]))
        out.append(m.group('s'))
        pos = m.end()
    out.append(re.sub(r'\$(\w+)', r'\1', s[pos:]))
    return ''.join(out)


_FUNCALL_RE = re.compile(r'\b(?P<name>[a-z_][a-z_0-9]*)\s*\(', re.IGNORECASE)


def _translate_function_calls(s: str) -> str:
    """Walk `s` and replace recognised PHP function calls with their
    Python equivalents. Iterates: each replacement may shift later
    positions, so we restart scanning after every substitution."""
    i = 0
    out = s
    safety = 200
    while safety > 0:
        safety -= 1
        m = _FUNCALL_RE.search(out, i)
        if not m:
            break
        name = m.group('name')
        if name not in _PHP_TO_PYTHON_FUNCS:
            i = m.end()
            continue
        repl_def = _PHP_TO_PYTHON_FUNCS[name]
        # Find the matching `)` for this call.
        open_paren = m.end() - 1
        close_paren = _balanced_paren(out, open_paren)
        if close_paren is None:
            i = m.end()
            continue
        args_src = out[open_paren + 1:close_paren]
        args = _split_args(args_src)
        if isinstance(repl_def, str):
            new = f'{repl_def}({", ".join(args)})' if args else f'{repl_def}()'
        else:
            try:
                new = repl_def(args)
            except Exception:
                new = None
            if new is None:
                # Wrong arity — leave the call untranslated for now.
                i = m.end()
                continue
        out = out[:m.start()] + new + out[close_paren + 1:]
        i = m.start() + len(new)
    return out


# ── Statement-level translation ───────────────────────────────────

def _translate_block(php_body: str, indent: int = 0) -> str:
    """Translate a PHP statement block into Python. `indent` is the
    Python indentation level (4-space units)."""
    lines: list[str] = []
    pad = '    ' * indent
    src = strip_php_comments(php_body)

    i = 0
    n = len(src)
    while i < n:
        # Skip whitespace
        while i < n and src[i] in ' \t\r\n':
            if src[i] == '\n':
                # Preserve blank line breaks
                lines.append('')
            i += 1
        if i >= n:
            break

        # Closing brace handled by caller — defensive.
        if src[i] == '}':
            i += 1; continue

        # Try block-form constructs first.
        block_match = _CONSTRUCT_RE.match(src, i)
        if block_match:
            kw = block_match.group('kw')
            if kw == 'if':
                rendered, new_i = _render_if(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'foreach':
                rendered, new_i = _render_foreach(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'for':
                rendered, new_i = _render_for(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'while':
                rendered, new_i = _render_while(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'switch':
                rendered, new_i = _render_switch(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'try':
                rendered, new_i = _render_try(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue
            if kw == 'function':
                rendered, new_i = _render_local_function(src, block_match, indent)
                lines.append(rendered)
                i = new_i
                continue

        # Otherwise, treat as a single statement up to the next
        # semicolon at depth-0 (respecting strings + nested parens).
        end = _find_statement_end(src, i)
        stmt = src[i:end].strip()
        if stmt.endswith(';'):
            stmt = stmt[:-1].rstrip()
        if stmt:
            lines.append(pad + _translate_simple_statement(stmt))
        i = end + 1

    return '\n'.join(lines)


def _find_statement_end(src: str, start: int) -> int:
    """Find the index of the `;` that terminates the statement
    starting at `start`, respecting string + paren + brace nesting."""
    depth = 0
    in_str: str | None = None
    i = start
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == '\\' and i + 1 < len(src):
                i += 2; continue
            if ch == in_str:
                in_str = None
            i += 1; continue
        if ch in ('"', "'"):
            in_str = ch; i += 1; continue
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        elif ch == ';' and depth == 0:
            return i
        i += 1
    return len(src)


_CONSTRUCT_RE = re.compile(
    r'\s*(?P<kw>if|for|foreach|while|switch|try|function)\b'
)


def _render_if(src: str, match: re.Match[str], indent: int
               ) -> tuple[str, int]:
    """Translate an if/elseif/else chain into Python's if/elif/else."""
    pad = '    ' * indent
    out: list[str] = []
    i = match.end()
    # Find the (cond)
    open_paren = src.find('(', i)
    if open_paren < 0:
        return pad + '# PORTER: malformed if', i
    close_paren = _balanced_paren(src, open_paren)
    if close_paren is None:
        return pad + '# PORTER: malformed if', i
    cond = src[open_paren + 1:close_paren]
    body_open = src.find('{', close_paren)
    if body_open < 0:
        return pad + '# PORTER: if without { }', close_paren + 1
    body_span = _balanced_block(src, body_open)
    if body_span is None:
        return pad + '# PORTER: unbalanced if body', close_paren + 1
    out.append(f'{pad}if {_translate_expr(cond)}:')
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    out.append(inner if inner.strip() else f'{pad}    pass')
    i = body_span[1] + 1
    # Look ahead for elseif / else
    while True:
        # Skip whitespace
        j = i
        while j < len(src) and src[j] in ' \t\r\n':
            j += 1
        if j >= len(src):
            i = j
            break
        # `elseif` first (longest match)
        if src.startswith('elseif', j) or src.startswith('else if', j):
            kw_end = j + (6 if src.startswith('elseif', j) else 7)
            op = src.find('(', kw_end)
            if op < 0:
                break
            cp = _balanced_paren(src, op)
            if cp is None:
                break
            cond = src[op + 1:cp]
            bo = src.find('{', cp)
            if bo < 0:
                break
            bs = _balanced_block(src, bo)
            if bs is None:
                break
            out.append(f'{pad}elif {_translate_expr(cond)}:')
            inner = _translate_block(src[bs[0]:bs[1]], indent + 1)
            out.append(inner if inner.strip() else f'{pad}    pass')
            i = bs[1] + 1
            continue
        if src.startswith('else', j):
            bo = src.find('{', j + 4)
            if bo < 0 or bo - (j + 4) > 5:  # else without immediate {
                break
            bs = _balanced_block(src, bo)
            if bs is None:
                break
            out.append(f'{pad}else:')
            inner = _translate_block(src[bs[0]:bs[1]], indent + 1)
            out.append(inner if inner.strip() else f'{pad}    pass')
            i = bs[1] + 1
        break
    return '\n'.join(out), i


def _render_foreach(src: str, match: re.Match[str], indent: int
                    ) -> tuple[str, int]:
    pad = '    ' * indent
    open_paren = src.find('(', match.end())
    close_paren = _balanced_paren(src, open_paren)
    if close_paren is None:
        return pad + '# PORTER: malformed foreach', match.end()
    inside = src[open_paren + 1:close_paren]
    # `arr as $v` or `arr as $k => $v`
    am = re.match(r'\s*(?P<arr>[^\s].*?)\s+as\s+(?P<binds>.+)$', inside,
                   re.DOTALL)
    if not am:
        return (pad + f'# PORTER: foreach({inside})',
                _find_statement_end(src, match.end()) + 1)
    arr = _translate_expr(am.group('arr').strip())
    binds = am.group('binds').strip()
    # k => v ?
    if '=>' in binds:
        k, v = [b.strip() for b in binds.split('=>', 1)]
        k = _strip_dollars_outside_strings(k)
        v = _strip_dollars_outside_strings(v)
        loop = f'for {k}, {v} in {arr}.items():'
    else:
        v = _strip_dollars_outside_strings(binds)
        loop = f'for {v} in {arr}:'
    body_open = src.find('{', close_paren)
    if body_open < 0:
        return pad + loop + ' pass', close_paren + 1
    body_span = _balanced_block(src, body_open)
    if body_span is None:
        return pad + loop + ' pass', close_paren + 1
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    return (f'{pad}{loop}\n' +
            (inner if inner.strip() else f'{pad}    pass'),
            body_span[1] + 1)


def _render_for(src: str, match: re.Match[str], indent: int
                ) -> tuple[str, int]:
    pad = '    ' * indent
    open_paren = src.find('(', match.end())
    close_paren = _balanced_paren(src, open_paren)
    if close_paren is None:
        return pad + '# PORTER: malformed for', match.end()
    parts = src[open_paren + 1:close_paren].split(';')
    # Try to recognise classic `for ($i = 0; $i < N; $i++)` shape.
    init_m = re.match(r'\s*\$(\w+)\s*=\s*(\d+)\s*$',
                       parts[0]) if parts else None
    cond_m = re.match(r'\s*\$(\w+)\s*<\s*(.+?)\s*$',
                       parts[1]) if len(parts) > 1 else None
    inc_m = re.match(r'\s*\$(\w+)\+\+\s*$',
                       parts[2]) if len(parts) > 2 else None
    body_open = src.find('{', close_paren)
    body_span = _balanced_block(src, body_open) if body_open >= 0 else None
    if body_span is None:
        return pad + '# PORTER: malformed for', close_paren + 1
    if init_m and cond_m and inc_m and \
       init_m.group(1) == cond_m.group(1) == inc_m.group(1):
        var = init_m.group(1)
        start_v = init_m.group(2)
        stop_v = _translate_expr(cond_m.group(2))
        line = f'for {var} in range({start_v}, {stop_v}):'
    else:
        line = (f'# PORTER: for ({src[open_paren + 1:close_paren]}) — '
                f'rewrite as Python loop')
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    return (f'{pad}{line}\n' +
            (inner if inner.strip() else f'{pad}    pass'),
            body_span[1] + 1)


def _render_while(src: str, match: re.Match[str], indent: int
                  ) -> tuple[str, int]:
    pad = '    ' * indent
    open_paren = src.find('(', match.end())
    close_paren = _balanced_paren(src, open_paren)
    if close_paren is None:
        return pad + '# PORTER: malformed while', match.end()
    cond = _translate_expr(src[open_paren + 1:close_paren])
    body_open = src.find('{', close_paren)
    body_span = _balanced_block(src, body_open) if body_open >= 0 else None
    if body_span is None:
        return pad + f'# PORTER: while ({cond})', close_paren + 1
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    return (f'{pad}while {cond}:\n' +
            (inner if inner.strip() else f'{pad}    pass'),
            body_span[1] + 1)


def _render_switch(src: str, match: re.Match[str], indent: int
                   ) -> tuple[str, int]:
    pad = '    ' * indent
    open_paren = src.find('(', match.end())
    close_paren = _balanced_paren(src, open_paren)
    if close_paren is None:
        return pad + '# PORTER: malformed switch', match.end()
    subject = _translate_expr(src[open_paren + 1:close_paren])
    body_open = src.find('{', close_paren)
    body_span = _balanced_block(src, body_open) if body_open >= 0 else None
    if body_span is None:
        return pad + f'# PORTER: switch ({subject})', close_paren + 1
    body = src[body_span[0]:body_span[1]]
    out = [f'{pad}match {subject}:']
    # Split on `case X:` / `default:` (but not `case` inside strings).
    parts = re.split(r'\b(case\s+[^:]+:|default\s*:)', body)
    # parts is alternating: [pre, label, code, label, code, ...]
    for j in range(1, len(parts), 2):
        label = parts[j].strip()
        code = parts[j + 1] if j + 1 < len(parts) else ''
        # Strip trailing `break;`
        code = re.sub(r'\bbreak\s*;', '', code)
        if label.startswith('case'):
            val = _translate_expr(label[4:-1].strip())
            out.append(f'{pad}    case {val}:')
        else:
            out.append(f'{pad}    case _:')
        case_inner = _translate_block(code, indent + 2)
        out.append(case_inner if case_inner.strip() else f'{pad}        pass')
    return '\n'.join(out), body_span[1] + 1


def _render_try(src: str, match: re.Match[str], indent: int
                ) -> tuple[str, int]:
    pad = '    ' * indent
    body_open = src.find('{', match.end())
    body_span = _balanced_block(src, body_open) if body_open >= 0 else None
    if body_span is None:
        return pad + '# PORTER: malformed try', match.end()
    out = [f'{pad}try:']
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    out.append(inner if inner.strip() else f'{pad}    pass')
    i = body_span[1] + 1
    # Optional catches
    while True:
        j = i
        while j < len(src) and src[j] in ' \t\r\n':
            j += 1
        if j >= len(src) or not src.startswith('catch', j):
            i = j
            break
        op = src.find('(', j + 5)
        cp = _balanced_paren(src, op) if op >= 0 else None
        if cp is None:
            break
        capture = src[op + 1:cp].strip()
        # `Exception $e` or `\\Foo\\Bar $e` or `Foo|Bar $e`
        cm = re.match(r'(?P<types>[\w\\|]+)\s+\$(?P<name>\w+)', capture)
        if cm:
            type_str = cm.group('types').replace('\\', '.').lstrip('.')
            type_str = type_str.replace('|', ', ')
            if ',' in type_str:
                type_str = f'({type_str})'
            out.append(f'{pad}except {type_str} as {cm.group("name")}:')
        else:
            out.append(f'{pad}except Exception:')
        bo = src.find('{', cp)
        bs = _balanced_block(src, bo) if bo >= 0 else None
        if bs is None:
            out.append(f'{pad}    pass')
            i = cp + 1
            continue
        case_inner = _translate_block(src[bs[0]:bs[1]], indent + 1)
        out.append(case_inner if case_inner.strip() else f'{pad}    pass')
        i = bs[1] + 1
    # Optional finally
    j = i
    while j < len(src) and src[j] in ' \t\r\n':
        j += 1
    if src.startswith('finally', j):
        bo = src.find('{', j + 7)
        bs = _balanced_block(src, bo) if bo >= 0 else None
        if bs is not None:
            out.append(f'{pad}finally:')
            case_inner = _translate_block(src[bs[0]:bs[1]], indent + 1)
            out.append(case_inner if case_inner.strip() else f'{pad}    pass')
            i = bs[1] + 1
    return '\n'.join(out), i


def _render_local_function(src: str, match: re.Match[str], indent: int
                           ) -> tuple[str, int]:
    pad = '    ' * indent
    name_m = re.match(r'\s*function\s+(?P<name>\w+)\s*\(', src[match.start():])
    if not name_m:
        return pad + '# PORTER: anonymous function', match.end()
    name = name_m.group('name')
    op = src.find('(', match.start() + name_m.start('name'))
    cp = _balanced_paren(src, op)
    if cp is None:
        return pad + '# PORTER: malformed function', match.end()
    args_src = src[op + 1:cp]
    args = _translate_php_param_list(args_src)
    body_open = src.find('{', cp)
    body_span = _balanced_block(src, body_open)
    if body_span is None:
        return pad + f'# PORTER: function {name}({args_src}) — no body', cp + 1
    inner = _translate_block(src[body_span[0]:body_span[1]], indent + 1)
    return (f'{pad}def {name}({args}):\n' +
            (inner if inner.strip() else f'{pad}    pass'),
            body_span[1] + 1)


def _translate_simple_statement(stmt: str) -> str:
    """Translate one assignment / expression / return / control
    keyword into Python."""
    s = stmt.strip()
    if not s:
        return ''
    # Standalone keywords
    if re.match(r'^(break|continue)\b', s):
        return re.match(r'^(break|continue)', s).group(0)
    if s == 'return' or re.match(r'^return\b', s):
        rest = s[6:].strip()
        if not rest:
            return 'return'
        return f'return {_translate_expr(rest)}'
    if re.match(r'^throw\b', s):
        rest = s[5:].strip()
        return f'raise {_translate_expr(rest)}'
    if re.match(r'^echo\b', s):
        rest = s[4:].strip()
        return f'print({_translate_expr(rest)})'
    if re.match(r'^global\b', s):
        rest = s[6:].strip()
        names = ', '.join(_strip_dollars_outside_strings(p).strip()
                          for p in rest.split(','))
        return f'global {names}'
    if re.match(r'^use\b', s):
        rest = s[3:].strip()
        return f'# PORTER: use {rest} — translate to a Python import'
    if re.match(r'^require(_once)?\b|^include(_once)?\b', s):
        return f'# PORTER: {s} — translate to import'
    # Assignment with `[]` push: `$arr[] = $x` → `arr.append(x)`
    m = re.match(r'^\$?(\w+)\s*\[\s*\]\s*=\s*(.+)$', s)
    if m:
        return f'{m.group(1)}.append({_translate_expr(m.group(2))})'
    # Chained array assignment: `$arr['key'] = expr`
    m = re.match(r'^\$?(\w+)\s*\[\s*(.+?)\s*\]\s*=\s*(.+)$', s)
    if m and not m.group(2).startswith('['):
        var = m.group(1)
        key = _translate_expr(m.group(2))
        val = _translate_expr(m.group(3))
        return f'{var}[{key}] = {val}'
    # Compound assignment (`.=` already handled in _translate_expr)
    return _translate_expr(s)


def _translate_php_param_list(args_src: str) -> str:
    if not args_src.strip():
        return ''
    out: list[str] = []
    for raw in _split_args(args_src):
        # Drop type hint, capture `$name`, optional default
        m = re.match(
            r'(?:(?:\??[\w\\|]+\s+)|(?:public|protected|private|readonly\s+))*'
            r'\$(?P<name>\w+)(?:\s*=\s*(?P<def>.+))?', raw,
        )
        if not m:
            continue
        name = m.group('name')
        if m.group('def'):
            out.append(f'{name}={_translate_expr(m.group("def").strip())}')
        else:
            out.append(name)
    return ', '.join(out)


# ── Top-level file parsing ────────────────────────────────────────

_NAMESPACE_RE = re.compile(r'^\s*namespace\s+([\w\\]+)\s*;', re.MULTILINE)
_USE_RE = re.compile(r'^\s*use\s+([\w\\]+(?:\s+as\s+\w+)?)\s*;', re.MULTILINE)
_TOPLEVEL_FUNC_RE = re.compile(
    r'(?:^|[\s;\}>])function\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*(?P<rt>\??[\w\\|]+))?\s*\{'
)
_TOPLEVEL_CLASS_RE = re.compile(
    r'(?:^|[\s;\}>])(?P<modifiers>(?:abstract\s+|final\s+)*)'
    r'class\s+(?P<name>\w+)'
    r'(?:\s+extends\s+(?P<parent>[\w\\]+))?'
    r'(?:\s+implements\s+(?P<impl>[\w\\,\s]+))?'
    r'\s*\{'
)
_METHOD_RE = re.compile(
    r'(?m)^\s*(?P<vis>public|protected|private)?\s*'
    r'(?P<static>static\s+)?'
    r'(?P<abstract>abstract\s+)?'
    r'(?P<final>final\s+)?'
    r'function\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)'
    r'(?:\s*:\s*(?P<rt>\??[\w\\|]+))?\s*(?:\{|;)'
)
_PROPERTY_RE = re.compile(
    r'(?m)^\s*(?P<vis>public|protected|private)\s+'
    r'(?:readonly\s+)?'
    r'(?:(?P<type>\??[\w\\|]+)\s+)?'
    r'\$(?P<name>\w+)(?:\s*=\s*(?P<default>[^;]+))?\s*;'
)
_CONST_RE = re.compile(
    r'(?m)^\s*(?:public\s+|protected\s+|private\s+)?'
    r'const\s+(?P<name>\w+)\s*=\s*(?P<value>[^;]+);'
)


def parse_file(php: str, source: Path | None = None) -> PhpFile:
    """Parse one PHP file into PhpFile records."""
    src = strip_php_comments(php)
    rec = PhpFile(source=source or Path('file.php'))
    nm = _NAMESPACE_RE.search(src)
    if nm:
        rec.namespace = nm.group(1)
    rec.uses = [m.group(1) for m in _USE_RE.finditer(src)]

    # Collect class and function spans so we can avoid double-parsing
    # class methods as top-level functions.
    class_spans: list[tuple[int, int]] = []

    for cm in _TOPLEVEL_CLASS_RE.finditer(src):
        body_open = src.find('{', cm.end() - 1)
        if body_open < 0:
            continue
        body_span = _balanced_block(src, body_open)
        if body_span is None:
            continue
        class_spans.append((cm.start(), body_span[1] + 1))
        class_body = src[body_span[0]:body_span[1]]
        cls = PhpClass(
            name=cm.group('name'),
            parent=(cm.group('parent') or '').replace('\\', '.').lstrip('.'),
            interfaces=[i.strip().replace('\\', '.').lstrip('.')
                        for i in (cm.group('impl') or '').split(',')
                        if i.strip()],
            is_abstract='abstract' in (cm.group('modifiers') or ''),
            is_final='final' in (cm.group('modifiers') or ''),
        )
        for pm in _PROPERTY_RE.finditer(class_body):
            cls.properties.append(PhpProperty(
                name=pm.group('name'),
                visibility=pm.group('vis'),
                type_hint=(pm.group('type') or ''),
                default=(_translate_expr(pm.group('default').strip())
                         if pm.group('default') else ''),
            ))
        for km in _CONST_RE.finditer(class_body):
            cls.constants.append((km.group('name'),
                                   _translate_expr(km.group('value').strip())))
        for mm in _METHOD_RE.finditer(class_body):
            method_name = mm.group('name')
            args_src = mm.group('args').strip()
            args = _translate_php_param_list(args_src)
            args_with_self = (f'self, {args}' if args else 'self')
            if mm.group('static'):
                args_with_self = args
            body_open_i = mm.end() - 1
            body_span2 = _balanced_block(class_body, body_open_i)
            php_body = (class_body[body_span2[0]:body_span2[1]]
                        if body_span2 else '')
            translated = _translate_block(php_body, indent=2) if php_body else \
                         '        pass'
            cls.methods.append(PhpFunction(
                name=method_name,
                args=args_with_self.split(', ') if args_with_self else [],
                body_python=translated,
                body_php=php_body,
                return_type=(mm.group('rt') or ''),
            ))
        rec.classes.append(cls)

    # Top-level functions, skipping any inside class spans.
    for fm in _TOPLEVEL_FUNC_RE.finditer(src):
        if any(s <= fm.start() < e for s, e in class_spans):
            continue
        body_open = src.find('{', fm.end() - 1)
        body_span = _balanced_block(src, body_open) if body_open >= 0 else None
        php_body = (src[body_span[0]:body_span[1]] if body_span else '')
        translated = _translate_block(php_body, indent=1) if php_body else \
                     '    pass'
        rec.functions.append(PhpFunction(
            name=fm.group('name'),
            args=_translate_php_param_list(fm.group('args').strip()).split(', ')
                 if fm.group('args').strip() else [],
            body_python=translated,
            body_php=php_body,
            return_type=(fm.group('rt') or ''),
        ))

    # Count porter markers across the whole translation.
    rec.porter_markers = (
        rec.top_level_python.count('# PORTER:')
        + sum(f.body_python.count('# PORTER:') for f in rec.functions)
        + sum(m.body_python.count('# PORTER:')
              for c in rec.classes for m in c.methods)
    )
    return rec


# ── Walker ────────────────────────────────────────────────────────

def parse_php_code(src_dir: Path) -> PhpCodeLiftResult:
    """Walk a directory of PHP source and parse every `.php` file."""
    result = PhpCodeLiftResult()
    if not src_dir.is_dir():
        return result
    for php_file in sorted(src_dir.rglob('*.php')):
        # Skip vendor + node_modules + tests by default.
        rel = php_file.relative_to(src_dir)
        if any(part in ('vendor', 'node_modules', 'tests', 'test')
               for part in rel.parts):
            continue
        try:
            text = php_file.read_text(encoding='utf-8', errors='replace')
        except OSError:
            result.skipped_files.append(rel)
            continue
        if not text.strip():
            result.skipped_files.append(rel)
            continue
        rec = parse_file(text, source=rel)
        if rec.functions or rec.classes:
            result.files.append(rec)
    return result


# ── Renderer ──────────────────────────────────────────────────────

def render_python(file_rec: PhpFile) -> str:
    """Render one PhpFile as a single Python source string."""
    out: list[str] = [
        f'"""Auto-translated from {file_rec.source} by datalift liftphpcode.',
        '',
        'Best-effort PHP → Python translation. # PORTER: markers',
        'flag lines that need human review.',
        '"""',
        '',
    ]
    if file_rec.namespace:
        out.append(f'# Original namespace: {file_rec.namespace}')
    if file_rec.uses:
        out.append('# Original use statements:')
        for u in file_rec.uses:
            out.append(f'#   use {u};')
    out.append('')
    out.append('import sys, os, math, json, base64, hashlib, time, datetime, '
               're, random, urllib.parse, html, functools')
    out.append('')

    for fn in file_rec.functions:
        args = ', '.join(a for a in fn.args if a)
        rt = f'  # returns: {fn.return_type}' if fn.return_type else ''
        out.append(f'def {fn.name}({args}):{rt}')
        out.append(fn.body_python or '    pass')
        out.append('')

    for cls in file_rec.classes:
        bases = []
        if cls.parent:
            bases.append(cls.parent)
        bases.extend(cls.interfaces)
        base_clause = f'({", ".join(bases)})' if bases else ''
        prefix = ''
        if cls.is_abstract:
            prefix = '# abstract — manually mark with @abstractmethod\n'
        out.append(f'{prefix}class {cls.name}{base_clause}:')
        any_body = False
        for cn, cv in cls.constants:
            out.append(f'    {cn} = {cv}')
            any_body = True
        for prop in cls.properties:
            default = prop.default if prop.default else 'None'
            out.append(f'    {prop.name} = {default}'
                       + (f'  # {prop.type_hint}' if prop.type_hint else ''))
            any_body = True
        for method in cls.methods:
            any_body = True
            args = ', '.join(a for a in method.args if a)
            rt = f'  # returns: {method.return_type}' if method.return_type \
                 else ''
            out.append(f'    def {method.name}({args}):{rt}')
            out.append(method.body_python or '        pass')
            out.append('')
        if not any_body:
            out.append('    pass')
        out.append('')

    return '\n'.join(out)


def render_worklist(result: PhpCodeLiftResult, app_label: str,
                    app_dir: Path) -> str:
    total_funcs = sum(len(f.functions) for f in result.files)
    total_classes = sum(len(f.classes) for f in result.files)
    total_methods = sum(len(c.methods) for f in result.files for c in f.classes)
    total_porter = sum(f.porter_markers for f in result.files)
    lines = [
        f'# liftphpcode worklist — {app_dir.name}',
        '',
        f'Target app: `{app_label}`. Generated by `datalift liftphpcode`.',
        '',
        f'## Coverage',
        '',
        f'- Files translated: **{len(result.files)}**',
        f'- Top-level functions: **{total_funcs}**',
        f'- Classes: **{total_classes}**',
        f'- Methods: **{total_methods}**',
        f'- `# PORTER:` markers (lines needing human review): '
        f'**{total_porter}**',
        f'- Files skipped (empty / unreadable / vendor / tests): '
        f'**{len(result.skipped_files)}**',
        '',
        '## Files',
        '',
    ]
    for f in result.files:
        lines.append(
            f'- `{f.source}` — {len(f.functions)} fn(s), '
            f'{len(f.classes)} class(es), '
            f'{f.porter_markers} porter marker(s)'
        )
    return '\n'.join(lines)


def apply(result: PhpCodeLiftResult, project_root: Path,
          app_label: str, dry_run: bool = False) -> list[str]:
    log: list[str] = []
    if not result.files:
        return log
    out_root = project_root / app_label / 'php_lifted'
    if not dry_run:
        out_root.mkdir(parents=True, exist_ok=True)
    for f in result.files:
        # Mirror the source path under php_lifted/, swapping .php→.py.
        target_rel = f.source.with_suffix('.py')
        target = out_root / target_rel
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(render_python(f), encoding='utf-8')
    log.append(f'php_lifted/ → {out_root.relative_to(project_root)} '
               f'({len(result.files)} file(s))')
    return log

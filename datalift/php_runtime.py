"""Runtime shims for PHP-semantics that don't translate to Python.

Lifted code imports from this module to bridge the semantic gap
between the two languages. The shims are intentionally small —
just enough to keep most translated code running without manual
edits. Where PHP and Python disagree subtly (loose equality,
truthiness, array semantics), the shim opts for the PHP behaviour.

Categories handled:

- **Truthiness / nullishness**: `php_isset`, `php_empty`, `php_eq`,
  `php_falsy` — PHP's `isset()`/`empty()`/`==` rules don't match
  Python's `is not None` / `not x` / `==`.
- **Counting**: `php_count` — PHP's `count(null)` returns 0;
  Python's `len(None)` raises.
- **Array helpers**: `PhpArray` — combined int/string-key
  ordered dict-like that mirrors PHP array semantics.
- **String fallbacks**: a few common cases where PHP allows
  operations Python doesn't.

The shim is small (~200 lines), pure Python, and has no external
dependencies. It does NOT reproduce all of PHP's semantics — only
the common subset that shows up in lifted code.
"""

from __future__ import annotations


def php_isset(*values) -> bool:
    """`isset($x)` returns True iff `$x` is declared and not null.
    In Python terms: every value is not None."""
    return all(v is not None for v in values)


def php_empty(value) -> bool:
    """`empty($x)` returns True for the values PHP considers empty:
    null, false, '', '0', 0, 0.0, [], {}. Notably `'0'` is empty
    in PHP but truthy in Python."""
    if value is None or value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str) and (value == '' or value == '0'):
        return True
    if isinstance(value, (list, tuple, dict, set)) and len(value) == 0:
        return True
    return False


def php_eq(a, b) -> bool:
    """PHP `==` (loose equality): cross-type comparisons coerce.
    Reproduces the most common cases:

    - `0 == "0"` → True
    - `null == false` → True
    - `null == 0` → True (PHP < 8 behaviour; PHP 8 changed this for
      string `'0'` only — we keep the older semantics for portability)
    - `"abc" == 0` → False (PHP 8+ behaviour; PHP 7 returned True)
    """
    if a is b:
        return True
    if a is None:
        return b is None or b is False or b == 0 or b == ''
    if b is None:
        return a is False or a == 0 or a == ''
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, str) and isinstance(b, (int, float)):
        try:
            return float(a) == float(b)
        except ValueError:
            return False
    if isinstance(b, str) and isinstance(a, (int, float)):
        try:
            return float(a) == float(b)
        except ValueError:
            return False
    return a == b


def php_neq(a, b) -> bool:
    return not php_eq(a, b)


def php_count(value) -> int:
    """`count(null)` returns 0 in PHP; `len(None)` raises in Python.
    Also handles `count(scalar) → 1` (PHP < 8 behaviour)."""
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 1


def php_strlen(value) -> int:
    if value is None:
        return 0
    return len(str(value))


def php_falsy(value) -> bool:
    """`if ($x)` in PHP — same rules as `empty()` but inverted."""
    return not php_empty(value)


# ── Superglobal wrappers ──────────────────────────────────────────
#
# `$_GET`, `$_POST`, `$_SERVER`, `$_SESSION`, `$_REQUEST`, `$_FILES`
# all become Python dict-likes the porter wires to Django's request.
# The shim provides empty defaults so module-level access doesn't
# crash before the porter wires the real source.

_GET: dict = {}
_POST: dict = {}
_REQUEST: dict = {}
_SERVER: dict = {}
_SESSION: dict = {}
_FILES: dict = {}
_COOKIE: dict = {}
_ENV: dict = {}


def bind_django_request(request) -> None:
    """Populate the shim superglobals from a Django request. Call
    this at the top of any view that uses lifted code."""
    global _GET, _POST, _REQUEST, _SERVER, _SESSION, _FILES, _COOKIE
    _GET = dict(request.GET)
    _POST = dict(request.POST)
    _REQUEST = {**_GET, **_POST}
    _SERVER = {k: v for k, v in request.META.items()
                if isinstance(v, (str, int, bool, type(None)))}
    _SESSION = dict(request.session)
    _FILES = dict(request.FILES) if hasattr(request, 'FILES') else {}
    _COOKIE = dict(request.COOKIES) if hasattr(request, 'COOKIES') else {}


# ── PHP-style array (combined dict + ordered list) ────────────────

class PhpArray(dict):
    """A dict that also supports integer-keyed sequential access
    and PHP's `[]=` push idiom. PHP arrays are ordered associative
    arrays where integer and string keys coexist; this shim
    approximates that."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_int = max(
            (k for k in self if isinstance(k, int)), default=-1) + 1

    def append(self, value) -> None:
        """`$arr[] = $value` in PHP."""
        self[self._next_int] = value
        self._next_int += 1

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        if isinstance(key, int) and key >= self._next_int:
            self._next_int = key + 1


# ── Output buffering (no-op shims) ────────────────────────────────
#
# PHP's `ob_start()` / `ob_get_clean()` are commonly used to
# capture output for later. Lifted code that calls these can use
# these no-op shims to compile; the porter rewires using
# `io.StringIO` + `contextlib.redirect_stdout` if real buffering
# matters.

def ob_start() -> None:
    """No-op shim for PHP `ob_start()`."""


def ob_get_clean() -> str:
    """No-op shim returning empty string."""
    return ''


def ob_end_clean() -> None:
    """No-op shim."""


def ob_get_contents() -> str:
    """No-op shim returning empty string."""
    return ''


# ── Misc PHP idioms ───────────────────────────────────────────────

def php_array_combine(keys, values) -> dict:
    """`array_combine($keys, $values)` → dict from two parallel lists."""
    return dict(zip(keys, values))


def php_array_fill(start_index: int, count: int, value) -> dict:
    """`array_fill($start, $count, $val)` → integer-keyed dict."""
    return {start_index + i: value for i in range(count)}


def php_explode(separator: str, string: str, limit: int | None = None) -> list:
    """`explode($sep, $str, $limit)` with the optional limit."""
    if limit is None:
        return string.split(separator)
    if limit < 0:
        return string.split(separator)[:limit] or []
    return string.split(separator, limit - 1) if limit > 0 else []


def php_implode(separator: str, parts) -> str:
    """`implode($sep, $arr)` — join string-coerced items."""
    return separator.join(str(p) for p in parts)


# Convenience aliases mirroring PHP function names so the AST
# lifter can do `from datalift.php_runtime import *` and have
# typical names available without further wiring.

isset = php_isset
empty = php_empty
count = php_count
strlen = php_strlen
explode = php_explode
implode = php_implode

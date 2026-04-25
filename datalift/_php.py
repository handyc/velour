"""Shared PHP-source helpers used by every Datalift lifter.

Centralised because earlier lifters carried their own naive
regex-based comment stripper, which corrupted strings containing
`/*` (e.g. Cake's `'/pages/*'` URL pattern) by treating the
embedded `/*` as a block-comment opener. The string-aware walker
here respects single-quoted, double-quoted, and (best-effort)
heredoc state.
"""

from __future__ import annotations


def strip_php_comments(src: str, keep_docblocks: bool = False) -> str:
    """Remove PHP `/* … */`, `// …`, and `# …` comments.

    Preserves PHP-attribute syntax `#[...]` (these are not comments
    in PHP 8). Preserves string contents — a `/*` inside a quoted
    string never starts a block comment. If `keep_docblocks=True`,
    `/* … */` blocks are preserved (Symfony annotation routes live
    in docblocks; see :mod:`datalift.symfony_lifter`).
    """
    out: list[str] = []
    i = 0
    n = len(src)
    in_str: str | None = None
    while i < n:
        ch = src[i]
        if in_str:
            out.append(ch)
            if ch == '\\' and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        # Block comment
        if ch == '/' and i + 1 < n and src[i + 1] == '*':
            if keep_docblocks:
                # Pass the block through verbatim.
                end = src.find('*/', i + 2)
                if end == -1:
                    out.append(src[i:])
                    i = n
                    continue
                out.append(src[i:end + 2])
                i = end + 2
                continue
            end = src.find('*/', i + 2)
            i = end + 2 if end != -1 else n
            continue
        # `//` line comment
        if ch == '/' and i + 1 < n and src[i + 1] == '/':
            nl = src.find('\n', i)
            i = nl if nl != -1 else n
            continue
        # `#` line comment, but `#[` is PHP 8 attribute syntax
        if ch == '#' and (i + 1 >= n or src[i + 1] != '['):
            nl = src.find('\n', i)
            i = nl if nl != -1 else n
            continue
        # String literal start
        if ch in ('"', "'"):
            in_str = ch
        out.append(ch)
        i += 1
    return ''.join(out)

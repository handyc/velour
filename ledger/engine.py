"""Ledger formula engines — registry + the default Excel-compatible one.

The contract every engine implements:

    class FormulaLanguageBase:
        slug: str
        def evaluate(self, formula: str, sheet_context: dict) -> Any
        def parse(self, formula: str)  # optional — for editor hints

`sheet_context` is ``{a1: value_or_text}`` — what the engine sees of the
sheet at evaluation time. ``value_or_text`` is the cell's
`computed_value` if the cell is a formula, otherwise its raw `value`,
both as strings. Engines decide how aggressively to coerce.

Phase 1 ships:
- ExcelFormulaLanguage — wraps the `formulas` pkg. SUM, IF, VLOOKUP,
  arithmetic, comparison — the standard kit. Heavyweight; one parser
  call per evaluate.
- ArithmeticFormulaLanguage — tiny safe-eval fallback supporting the
  four operations + cell refs. Useful as a smoke-test target and as
  proof that the registry plugs in cleanly.

Phase 2 will add a per-language AST and incremental dirty-cell
recompute. For Phase 1 we recompute the touched cell only.
"""

import re

from .models import letter_to_col


CELL_REF_RE = re.compile(r'\b([A-Z]+)([0-9]+)\b')


class FormulaLanguageBase:
    slug = 'base'

    def evaluate(self, formula, sheet_context):
        raise NotImplementedError


class ArithmeticFormulaLanguage(FormulaLanguageBase):
    """Cell refs + the four operations. No functions. Strict.

    Lives here so the registry can be exercised end-to-end with no
    `formulas` dependency in sight — and as a demonstration of how
    cheap a custom language is to add.
    """

    slug = 'arith'

    SAFE_BUILTINS = {'__builtins__': {}}

    def evaluate(self, formula, sheet_context):
        expr = self._substitute_refs(formula, sheet_context)
        # Reject anything outside digits, operators, dots, parens, spaces.
        if not re.fullmatch(r'[\d+\-*/().\s]+', expr or ''):
            raise ValueError('non-arithmetic content after substitution')
        return eval(expr, self.SAFE_BUILTINS, {})  # noqa: S307 — see filter above

    def _substitute_refs(self, formula, ctx):
        def sub(m):
            a1 = m.group(0)
            v = ctx.get(a1, '')
            if v == '' or v is None:
                return '0'
            return str(v)
        return CELL_REF_RE.sub(sub, formula)


class ExcelFormulaLanguage(FormulaLanguageBase):
    """Excel-formula-compatible evaluator backed by the `formulas` pkg.

    Recompute model: build a one-cell parser, hand it the surrounding
    sheet's values as inputs, return the single output. Per-cell rebuild
    is wasteful at workbook scale but trivially correct for Phase 1.
    """

    slug = 'excel'

    def evaluate(self, formula, sheet_context):
        import formulas  # local — heavy dep; load on demand
        target = 'Sheet1!Z9999'  # synthetic target cell
        expr = f'={formula}' if not formula.startswith('=') else formula
        # The `formulas` package eats workbook-shape input; we synthesise
        # a one-cell sheet whose inputs include all referenced A1's.
        inputs = {}
        for m in CELL_REF_RE.finditer(formula):
            a1 = m.group(0)
            v = sheet_context.get(a1, '')
            inputs[f'Sheet1!{a1}'] = self._coerce(v)
        try:
            xl = formulas.Parser().ast(expr)[1].compile()
        except Exception as e:
            raise ValueError(f'parse error: {e}')
        try:
            result = xl(**{
                k.replace('!', '!').replace('Sheet1!', ''): v
                for k, v in inputs.items()
            })
        except TypeError:
            # The compiled callable's input names depend on the formula.
            # Fall back to passing positional inputs in order.
            result = xl(*inputs.values())
        # `formulas` returns numpy scalars; make them stringifiable.
        try:
            return result.item()
        except AttributeError:
            return result

    def _coerce(self, v):
        if v is None or v == '':
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
        return v


# Registry — `slug` → instance. New languages register themselves here.
LANGUAGES = {
    ArithmeticFormulaLanguage.slug: ArithmeticFormulaLanguage(),
    ExcelFormulaLanguage.slug: ExcelFormulaLanguage(),
}


def evaluate_cell(formula, sheet_context, language_slug='excel'):
    """Top-level helper used by views. Returns (value, error or None)."""
    engine = LANGUAGES.get(language_slug) or LANGUAGES['excel']
    try:
        return engine.evaluate(formula, sheet_context), None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def build_sheet_context(sheet):
    """Build the {a1: value-or-computed} map an engine needs."""
    from .models import col_to_letter
    ctx = {}
    for c in sheet.cells.all():
        a1 = col_to_letter(c.col) + str(c.row + 1)
        if c.is_formula():
            ctx[a1] = c.computed_value
        else:
            ctx[a1] = c.value
    return ctx

"""Safe JSON condition evaluator for Identity rules.

Conditions are small JSON trees with three shapes:

  Leaf:    {"metric": "disk.used_pct", "op": ">", "value": 0.95}
  All-of:  {"all": [leaf, leaf, ...]}
  Any-of:  {"any": [leaf, leaf, ...]}

`metric` is a dot-notation path into the sensor snapshot dict. The
evaluator walks the path left to right; any missing key short-circuits
the condition to False rather than raising.

`op` is one of: ==, !=, >, >=, <, <=, in (for membership — value is a
list, and the metric value must appear in it).

`value` is any JSON-serializable constant. No expressions, no name
lookups, no callables. Rule authors who want a threshold expressed as
a function of host config (like "load_1 > cpu_cores * 1.5") should
bake the number into `value` at author time. This limits dynamism but
removes an entire class of security footguns — the worst thing a
malformed condition can do is return False.
"""

OPERATORS = {
    '==': lambda a, b: a == b,
    '!=': lambda a, b: a != b,
    '>':  lambda a, b: a > b,
    '>=': lambda a, b: a >= b,
    '<':  lambda a, b: a < b,
    '<=': lambda a, b: a <= b,
    'in': lambda a, b: a in b if hasattr(b, '__contains__') else False,
}


def _resolve_metric(snapshot, path):
    """Walk a dotted path through nested dicts. Returns None if any
    intermediate key is missing OR if the traversal hits a non-dict
    before the leaf."""
    if not path:
        return None
    cur = snapshot
    for part in path.split('.'):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def evaluate(condition, snapshot):
    """Evaluate a condition against a sensor snapshot. Returns True
    iff the condition matches. Any error returns False — rules that
    can't evaluate cleanly are treated as not matching, so a broken
    rule can never crash the tick pipeline."""
    if not isinstance(condition, dict) or not condition:
        return False

    try:
        if 'all' in condition:
            clauses = condition['all']
            return isinstance(clauses, list) and all(
                evaluate(c, snapshot) for c in clauses
            )
        if 'any' in condition:
            clauses = condition['any']
            return isinstance(clauses, list) and any(
                evaluate(c, snapshot) for c in clauses
            )

        metric = condition.get('metric')
        op = condition.get('op', '==')
        value = condition.get('value')

        if not metric or op not in OPERATORS:
            return False

        actual = _resolve_metric(snapshot, metric)
        if actual is None:
            return False

        return OPERATORS[op](actual, value)
    except (TypeError, ValueError, KeyError):
        return False

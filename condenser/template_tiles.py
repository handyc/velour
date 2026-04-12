"""Template tiles — Wang-tile-inspired code templates for guaranteed translation.

Each template is a "tile" with typed edges:
  - North edge: what type this template expects as INPUT
  - South edge: what type this template PRODUCES as output
  - East/West: how it connects to adjacent templates in the data flow

If the template set is COMPLETE (has a tile for every edge combination
that appears in the IR), then translation is GUARANTEED to succeed —
just like a complete Wang tileset can tile any plane.

Edge types: void, int, float, str, bool, list, json, html, pin

A template is a function: (tier, input_type, output_type) → code string.
The Condenser's job is to:
  1. Walk the IR's data flow
  2. At each step, find the template whose edges match
  3. Emit the template's code
  4. The edges guarantee the next template will also match

This is the Wang tile insight: precomputed routes for every possible
connection. No creativity needed. No AI needed. Just matching.
"""


# Edge types that appear in IR data flows
EDGE_TYPES = ['void', 'int', 'float', 'str', 'bool', 'list', 'json', 'html', 'pin']


def _t(tier, code):
    """Wrap a code string with its tier."""
    return code


# =====================================================================
# Template tile registry
# =====================================================================
# Key: (tier, input_type, output_type, operation)
# Value: code template (with {field}, {model}, {value} placeholders)

TILES = {}


def tile(tier, input_type, output_type, operation):
    """Decorator to register a template tile."""
    def wrapper(fn):
        TILES[(tier, input_type, output_type, operation)] = fn
        return fn
    return wrapper


def lookup(tier, input_type, output_type, operation):
    """Find a matching template tile. Returns the template function or None."""
    # Exact match
    key = (tier, input_type, output_type, operation)
    if key in TILES:
        return TILES[key]
    # Try with 'any' input
    key = (tier, 'any', output_type, operation)
    if key in TILES:
        return TILES[key]
    # Try with 'any' output
    key = (tier, input_type, 'any', operation)
    if key in TILES:
        return TILES[key]
    # Universal fallback
    key = (tier, 'any', 'any', operation)
    if key in TILES:
        return TILES[key]
    return None


def coverage_report(tier):
    """Show which (input, output, op) combinations have tiles."""
    ops = set()
    for (t, i, o, op) in TILES:
        if t == tier:
            ops.add((i, o, op))
    return ops


# =====================================================================
# JS tiles (Tier 2)
# =====================================================================

@tile('js', 'void', 'list', 'read_all')
def js_read_all(model, field=None, **kw):
    return f'var items = list_{model.lower()}();'

@tile('js', 'str', 'any', 'read_one')
def js_read_one(model, field='id', **kw):
    return f'var item = get_{model.lower()}({field});'

@tile('js', 'any', 'void', 'write')
def js_write(model, **kw):
    return f'create_{model.lower()}(obj);'

@tile('js', 'any', 'void', 'delete')
def js_delete(model, **kw):
    return f'delete_{model.lower()}(id);'

@tile('js', 'list', 'html', 'render_list')
def js_render_list(model, fields=None, **kw):
    if not fields:
        fields = ['name', 'id']
    cols = ''.join(f'<th>{f}</th>' for f in fields)
    cells = ''.join(f'" + item.{f} + "' for f in fields)
    return (f'var h = "<table><tr>{cols}</tr>";'
            f'items.forEach(function(item){{ h += "<tr><td>{cells}</td></tr>"; }});'
            f'h += "</table>";')

@tile('js', 'any', 'html', 'render_form')
def js_render_form(model, fields=None, **kw):
    if not fields:
        return 'var h = "<form>No fields</form>";'
    rows = ''.join(
        f'<div class=\\"form-row\\"><label>{f}</label>'
        f'<input id=\\"f_{f}\\" type=\\"text\\"></div>'
        for f in fields
    )
    return f'var h = "<form>{rows}<button type=\\"submit\\">Save</button></form>";'

@tile('js', 'any', 'str', 'read_field')
def js_read_field(model=None, field='value', **kw):
    return f'var val = document.getElementById("f_{field}").value;'

@tile('js', 'int', 'str', 'to_string')
def js_int_to_str(**kw):
    return 'var s = String(val);'

@tile('js', 'str', 'int', 'to_int')
def js_str_to_int(**kw):
    return 'var n = parseInt(val) || 0;'


# =====================================================================
# ESP tiles (Tier 3)
# =====================================================================

@tile('esp', 'void', 'html', 'serve_page')
def esp_serve(model=None, **kw):
    return 'server.send_P(200, "text/html", PAGE);'

@tile('esp', 'str', 'void', 'serial_print')
def esp_serial(model=None, field='msg', **kw):
    return f'Serial.println({field});'

@tile('esp', 'void', 'int', 'read_adc')
def esp_read_adc(model=None, field='A0', **kw):
    return f'int val = analogRead({field});'

@tile('esp', 'int', 'void', 'write_pin')
def esp_write_pin(model=None, field='D0', **kw):
    return f'digitalWrite({field}, val);'


# =====================================================================
# ATTiny tiles (Tier 4)
# =====================================================================

@tile('attiny', 'void', 'int', 'read_pin')
def attiny_read_pin(model=None, field='PB0', **kw):
    return f'uint8_t val = (PINB >> {field}) & 1;'

@tile('attiny', 'int', 'void', 'write_pin')
def attiny_write_pin(model=None, field='PB2', **kw):
    return f'if (val) PORTB |= (1 << {field}); else PORTB &= ~(1 << {field});'

@tile('attiny', 'int', 'int', 'lookup')
def attiny_lookup(model=None, field='LUT', **kw):
    return f'uint8_t result = pgm_read_byte(&{field}[val]);'

@tile('attiny', 'void', 'int', 'read_adc')
def attiny_read_adc(model=None, field='3', **kw):
    return (f'ADMUX = {field}; ADCSRA |= (1 << ADSC); '
            f'while (ADCSRA & (1 << ADSC)); uint16_t val = ADC;')


# =====================================================================
# 555 tiles (Tier 5) — "code" is circuit descriptions
# =====================================================================

@tile('circuit', 'void', 'int', 'read_voltage')
def circuit_read(model=None, field='input', **kw):
    return f'Wire from {field} → comparator non-inverting input'

@tile('circuit', 'int', 'int', 'compare')
def circuit_compare(model=None, field='threshold', **kw):
    return f'LM393: if V > {field} then output HIGH'

@tile('circuit', 'int', 'void', 'drive_output')
def circuit_drive(model=None, field='LED', **kw):
    return f'Comparator output → 2N2222 base → {field}'

@tile('circuit', 'void', 'int', 'oscillate')
def circuit_oscillate(model=None, field='500ms', **kw):
    return f'NE555 astable: R1=22k R2=27k C=10µF → {field} period'


def translate_step(tier, step, ir):
    """Translate one IR LogicStep using the template tiles.

    This is the Wang tile matching: find a template whose edges
    match the step's input/output types. If the template set is
    complete, this always succeeds.
    """
    # Determine input/output types from the step
    op_map = {
        'read': ('void', 'list', 'read_all'),
        'write': ('any', 'void', 'write'),
        'render': ('list', 'html', 'render_list'),
        'output': ('int', 'void', 'write_pin'),
        'redirect': ('void', 'void', 'redirect'),
        'compute': ('any', 'any', 'compute'),
    }
    in_t, out_t, op = op_map.get(step.op, ('any', 'any', step.op))

    fn = lookup(tier, in_t, out_t, op)
    if fn:
        return fn(model=step.target, field=step.target)
    return f'// NO TILE for ({tier}, {in_t}, {out_t}, {op})'

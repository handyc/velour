"""Tier 2 generator: AppIR → standalone JS/HTML page.

Produces a working single-file HTML application from the IR.
Models become localStorage-backed objects. Views become JS functions.
Routes become onclick handlers. CRUD operations work.

The output is a real, runnable web app — not a mockup.
"""

from .capabilities import filter_ir_for_tier


def generate(ir):
    """Generate a standalone HTML/JS page from an AppIR."""
    fir = filter_ir_for_tier(ir, 'js')

    parts = []
    parts.append(_html_head(fir))
    parts.append(_js_storage(fir))
    parts.append(_js_crud(fir))
    parts.append(_js_views(fir))
    parts.append(_js_router(fir))
    parts.append(_js_app_specific(fir))
    parts.append(_js_init(fir))
    parts.append(_html_foot())

    return '\n'.join(parts)


def _html_head(ir):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{ir.name} — Condensed</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0d1117;color:#c9d1d9;font-family:system-ui,sans-serif;padding:1rem;font-size:0.85rem}}
h1{{font-size:1.1rem;color:#58a6ff;margin-bottom:0.5rem}}
h2{{font-size:0.9rem;margin:0.6rem 0 0.3rem}}
.nav{{display:flex;gap:0.4rem;margin:0.5rem 0;flex-wrap:wrap}}
.nav a{{color:#58a6ff;font-size:0.78rem;cursor:pointer;text-decoration:underline}}
table{{width:100%;border-collapse:collapse;font-size:0.78rem;margin:0.3rem 0}}
th{{text-align:left;color:#8b949e;border-bottom:1px solid #30363d;padding:0.2rem 0.4rem;font-size:0.7rem}}
td{{padding:0.2rem 0.4rem;border-bottom:1px solid #161b22}}
.form-row{{margin:0.3rem 0;display:flex;gap:0.3rem;align-items:center}}
.form-row label{{font-size:0.72rem;color:#8b949e;min-width:5rem}}
input,select,textarea{{background:#161b22;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:0.2rem 0.4rem;font-size:0.78rem}}
button{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:3px;padding:0.2rem 0.6rem;font-size:0.75rem;cursor:pointer}}
button:hover{{background:#30363d}}
button.primary{{background:#238636;border-color:#2ea043}}
button.danger{{background:#da3633;border-color:#f85149;font-size:0.65rem}}
#app{{min-height:200px}}
.dim{{color:#6e7681;font-size:0.7rem}}
</style>
</head>
<body>
<h1>{ir.name} — Condensed</h1>
<p class="dim">Auto-generated from Django IR. {len(ir.models)} models, {len(ir.views)} views. Data in localStorage.</p>
<div class="nav" id="nav"></div>
<div id="app"></div>
'''


def _html_foot():
    return '</body>\n</html>'


def _js_storage(ir):
    """Generate localStorage-backed storage for each model."""
    lines = ['<script>', '// --- Storage (localStorage) ---']
    lines.append('var DB = {};')

    for model in ir.models:
        key = model.name.lower()
        lines.append(f'DB.{key} = JSON.parse(localStorage.getItem("c_{key}") || "[]");')

    lines.append('function dbSave(key) { localStorage.setItem("c_" + key, JSON.stringify(DB[key])); }')
    lines.append('var _nextId = Date.now();')
    lines.append('function nextId() { return _nextId++; }')
    lines.append('')
    return '\n'.join(lines)


def _js_crud(ir):
    """Generate CRUD functions for each model."""
    lines = ['// --- CRUD ---']

    for model in ir.models:
        key = model.name.lower()
        fields = [f.name for f in model.fields if f.name != 'id']

        # Create
        lines.append(f'function create_{key}(obj) {{')
        lines.append(f'  obj.id = nextId();')
        lines.append(f'  DB.{key}.push(obj);')
        lines.append(f'  dbSave("{key}");')
        lines.append(f'  return obj;')
        lines.append(f'}}')

        # Read all
        lines.append(f'function list_{key}() {{ return DB.{key}; }}')

        # Read one
        lines.append(f'function get_{key}(id) {{ return DB.{key}.find(function(x){{ return x.id == id; }}); }}')

        # Delete
        lines.append(f'function delete_{key}(id) {{')
        lines.append(f'  DB.{key} = DB.{key}.filter(function(x){{ return x.id != id; }});')
        lines.append(f'  dbSave("{key}");')
        lines.append(f'}}')
        lines.append('')

    return '\n'.join(lines)


def _js_views(ir):
    """Generate view functions that render into #app."""
    lines = ['// --- Views ---']

    for model in ir.models:
        key = model.name.lower()
        fields = [f for f in model.fields if f.name not in ('id', 'created_at', 'updated_at')]

        # List view
        lines.append(f'function view_list_{key}() {{')
        lines.append(f'  var items = list_{key}();')
        lines.append(f'  var h = "<h2>{model.name} (" + items.length + ")</h2>";')
        lines.append(f'  h += \'<button class="primary" onclick="view_add_{key}()">Add</button>\';')
        lines.append(f'  h += "<table><tr>";')
        for f in fields[:8]:  # limit visible columns
            lines.append(f'  h += "<th>{f.name}</th>";')
        lines.append(f'  h += "<th></th></tr>";')
        lines.append(f'  items.forEach(function(item) {{')
        lines.append(f'    h += "<tr>";')
        for f in fields[:8]:
            lines.append(f'    h += "<td>" + (item.{f.name} != null ? item.{f.name} : "") + "</td>";')
        lines.append(f'    h += \'<td><button class="danger" onclick="delete_{key}(\' + item.id + \');view_list_{key}()">×</button></td>\';')
        lines.append(f'    h += "</tr>";')
        lines.append(f'  }});')
        lines.append(f'  h += "</table>";')
        lines.append(f'  document.getElementById("app").innerHTML = h;')
        lines.append(f'}}')
        lines.append('')

        # Add/create form view
        lines.append(f'function view_add_{key}() {{')
        lines.append(f'  var h = "<h2>Add {model.name}</h2>";')
        lines.append(f'  h += \'<form onsubmit="return save_new_{key}()">\';')
        for f in fields:
            if f.name in ('created_at', 'updated_at'):
                continue
            if f.choices:
                lines.append(f'  h += \'<div class="form-row"><label>{f.name}</label><select id="f_{f.name}">\';')
                for c in f.choices:
                    lines.append(f'  h += \'<option value="{c}">{c}</option>\';')
                lines.append(f'  h += "</select></div>";')
            elif f.type == 'bool':
                lines.append(f'  h += \'<div class="form-row"><label>{f.name}</label><input type="checkbox" id="f_{f.name}"></div>\';')
            elif f.type in ('int', 'float'):
                lines.append(f'  h += \'<div class="form-row"><label>{f.name}</label><input type="number" id="f_{f.name}" value="0"></div>\';')
            else:
                lines.append(f'  h += \'<div class="form-row"><label>{f.name}</label><input type="text" id="f_{f.name}"></div>\';')
        lines.append(f'  h += \'<div class="form-row"><button type="submit" class="primary">Save</button>\';')
        lines.append(f'  h += \'<button type="button" onclick="view_list_{key}()">Cancel</button></div>\';')
        lines.append(f'  h += "</form>";')
        lines.append(f'  document.getElementById("app").innerHTML = h;')
        lines.append(f'}}')
        lines.append('')

        # Save handler
        lines.append(f'function save_new_{key}() {{')
        lines.append(f'  var obj = {{}};')
        for f in fields:
            if f.name in ('created_at', 'updated_at'):
                lines.append(f'  obj.{f.name} = new Date().toISOString();')
            elif f.type == 'bool':
                lines.append(f'  obj.{f.name} = document.getElementById("f_{f.name}").checked;')
            elif f.type in ('int', 'float'):
                lines.append(f'  obj.{f.name} = Number(document.getElementById("f_{f.name}").value);')
            else:
                lines.append(f'  obj.{f.name} = document.getElementById("f_{f.name}").value;')
        lines.append(f'  create_{key}(obj);')
        lines.append(f'  view_list_{key}();')
        lines.append(f'  return false;')
        lines.append(f'}}')
        lines.append('')

    return '\n'.join(lines)


def _js_router(ir):
    """Generate navigation."""
    lines = ['// --- Navigation ---']
    lines.append('function renderNav() {')
    lines.append('  var h = "";')
    for model in ir.models:
        key = model.name.lower()
        lines.append(f'  h += \'<a onclick="view_list_{key}()">{model.name}</a>\';')
    lines.append('  document.getElementById("nav").innerHTML = h;')
    lines.append('}')
    return '\n'.join(lines)


def _js_app_specific(ir):
    """App-specific rendering code."""
    from .app_specific import get_app_renderer
    code = get_app_renderer(ir.name)
    if code:
        return f'// --- App-specific rendering ---\n{code}'
    return ''


def _js_init(ir):
    """Startup code."""
    first_model = ir.models[0].name.lower() if ir.models else ''
    lines = ['// --- Init ---']
    lines.append('renderNav();')
    if first_model:
        lines.append(f'view_list_{first_model}();')
    lines.append('</script>')
    return '\n'.join(lines)

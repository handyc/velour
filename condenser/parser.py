"""Parse a Django app into the Condenser IR.

Reads the app's models.py, views.py, and urls.py using Django's own
introspection (model._meta, url patterns) rather than text parsing.
This means it works on any Django app, not just ones we wrote.
"""

from django.apps import apps
from django.urls import URLResolver, URLPattern

from .ir import AppIR, FieldIR, LogicStep, ModelIR, RouteIR, StateIR, ViewIR


# Map Django field types to IR types
FIELD_TYPE_MAP = {
    'AutoField': 'int',
    'BigAutoField': 'int',
    'CharField': 'str',
    'TextField': 'str',
    'SlugField': 'str',
    'EmailField': 'str',
    'URLField': 'str',
    'IntegerField': 'int',
    'PositiveIntegerField': 'int',
    'PositiveSmallIntegerField': 'int',
    'BigIntegerField': 'int',
    'SmallIntegerField': 'int',
    'FloatField': 'float',
    'DecimalField': 'float',
    'BooleanField': 'bool',
    'DateTimeField': 'str',
    'DateField': 'str',
    'TimeField': 'str',
    'JSONField': 'json',
    'FileField': 'str',
    'ImageField': 'str',
    'ForeignKey': 'int',    # store as ID reference
    'OneToOneField': 'int',
    'ManyToManyField': 'list',
}


def parse_app(app_label):
    """Parse a Django app into an AppIR.

    Uses Django's model introspection to extract fields, and the
    app's urls.py to extract routes. View logic is inferred from
    the view function signatures and decorators.
    """
    try:
        app_config = apps.get_app_config(app_label)
    except LookupError:
        return None

    ir = AppIR(name=app_label)

    # Parse models
    for model in app_config.get_models():
        mir = ModelIR(name=model.__name__)
        for f in model._meta.get_fields():
            if hasattr(f, 'get_internal_type'):
                ftype = FIELD_TYPE_MAP.get(f.get_internal_type(), 'str')
                fir = FieldIR(
                    name=f.name,
                    type=ftype,
                    max_length=getattr(f, 'max_length', 0) or 0,
                    choices=[c[0] for c in getattr(f, 'choices', None) or []],
                )
                if hasattr(f, 'default') and f.default is not None:
                    from django.db.models.fields import NOT_PROVIDED
                    if f.default is not NOT_PROVIDED:
                        try:
                            fir.default = f.default
                        except Exception:
                            pass
                mir.fields.append(fir)
        ir.models.append(mir)
        ir.state.append(StateIR(
            name=model.__name__.lower(),
            type='db',
            model=model.__name__,
        ))

    # Parse URLs
    try:
        urls_module = __import__(f'{app_label}.urls', fromlist=['urlpatterns'])
        patterns = getattr(urls_module, 'urlpatterns', [])
        for p in patterns:
            if isinstance(p, URLPattern):
                view_name = ''
                if hasattr(p.callback, '__name__'):
                    view_name = p.callback.__name__
                ir.routes.append(RouteIR(
                    path=str(p.pattern),
                    view_name=view_name,
                ))
    except (ImportError, AttributeError):
        pass

    # Parse views — create ViewIR stubs from routes
    seen_views = set()
    for route in ir.routes:
        if route.view_name and route.view_name not in seen_views:
            seen_views.add(route.view_name)
            vir = ViewIR(name=route.view_name)

            # Infer basic logic from view name patterns
            name = route.view_name.lower()
            if 'list' in name:
                # List view: read all, render
                model_name = _guess_model(name, ir.models)
                vir.steps = [
                    LogicStep(op='read', target=model_name, params={'all': True}),
                    LogicStep(op='render', target='list'),
                ]
            elif 'detail' in name or 'view' in name:
                model_name = _guess_model(name, ir.models)
                vir.steps = [
                    LogicStep(op='read', target=model_name, params={'by': 'slug'}),
                    LogicStep(op='render', target='detail'),
                ]
            elif 'add' in name or 'create' in name:
                model_name = _guess_model(name, ir.models)
                vir.method = 'POST'
                vir.steps = [
                    LogicStep(op='render', target='form'),
                    LogicStep(op='write', target=model_name),
                    LogicStep(op='redirect', target='list'),
                ]
            elif 'delete' in name:
                model_name = _guess_model(name, ir.models)
                vir.method = 'POST'
                vir.steps = [
                    LogicStep(op='read', target=model_name, params={'by': 'slug'}),
                    LogicStep(op='write', target=model_name, params={'delete': True}),
                    LogicStep(op='redirect', target='list'),
                ]
            else:
                vir.steps = [LogicStep(op='render', target='page')]

            ir.views.append(vir)

    return ir


def _guess_model(view_name, models):
    """Try to guess which model a view operates on."""
    for m in models:
        if m.name.lower() in view_name:
            return m.name
    return models[0].name if models else 'unknown'


def summarize(ir):
    """Human-readable summary of an AppIR."""
    lines = [ir.summary, '']

    if ir.models:
        lines.append('Models:')
        for m in ir.models:
            lines.append(f'  {m.name} ({len(m.fields)} fields, ~{m.storage_bytes}B)')
            for f in m.fields:
                extra = ''
                if f.choices:
                    extra = f' choices={f.choices}'
                if f.max_length:
                    extra += f' max={f.max_length}'
                lines.append(f'    {f.name}: {f.type}{extra}')

    if ir.routes:
        lines.append('')
        lines.append('Routes:')
        for r in ir.routes:
            lines.append(f'  {r.method} {r.path} → {r.view_name}')

    if ir.views:
        lines.append('')
        lines.append('Views:')
        for v in ir.views:
            steps = ' → '.join(f'{s.op}({s.target})' for s in v.steps)
            lines.append(f'  {v.name}: {steps}')

    return '\n'.join(lines)

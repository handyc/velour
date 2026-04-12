"""Condenser Intermediate Representation (IR).

The IR is the bridge between tiers. It captures the *semantic content*
of an app — what data it holds, what logic it performs, what it shows —
without committing to any particular implementation.

A Django app is parsed INTO the IR. Target-tier code is generated FROM
the IR. The IR is the thing that's actually being condensed.

Structure:
    AppIR
    ├── models: list of ModelIR
    │   └── fields: list of FieldIR (name, type, default)
    ├── views: list of ViewIR
    │   └── logic: list of LogicStep (read, compute, render)
    ├── routes: list of RouteIR (path → view name)
    └── state: list of StateIR (what needs to persist between requests)

Each tier generator reads the IR and produces working output:
    - Tier 2 (JS): models→localStorage, views→functions, routes→onclick
    - Tier 3 (ESP): models→PROGMEM, views→handlers, routes→server.on()
    - Tier 4 (ATTiny): models→SRAM, views→main loop, routes→pin reads
    - Tier 5 (555): models→RC values, views→comparator networks
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldIR:
    """One field in a model."""
    name: str
    type: str           # 'str', 'int', 'float', 'bool', 'list', 'json'
    default: Any = None
    max_length: int = 0
    choices: list = field(default_factory=list)


@dataclass
class ModelIR:
    """One data model (table/struct/variable set)."""
    name: str
    fields: list = field(default_factory=list)  # list of FieldIR

    @property
    def storage_bytes(self):
        """Estimate storage needed at the lowest tier."""
        total = 0
        for f in self.fields:
            if f.type == 'bool':
                total += 1
            elif f.type == 'int':
                total += 2
            elif f.type == 'float':
                total += 4
            elif f.type == 'str':
                total += f.max_length or 32
            else:
                total += 8
        return total


@dataclass
class LogicStep:
    """One step in a view's logic."""
    op: str             # 'read', 'write', 'compute', 'filter', 'render', 'redirect'
    target: str = ''    # model name, field name, or template name
    params: dict = field(default_factory=dict)


@dataclass
class ViewIR:
    """One view (page/handler/function)."""
    name: str
    method: str = 'GET'         # GET or POST
    steps: list = field(default_factory=list)  # list of LogicStep
    template: str = ''          # template content or reference
    renders: list = field(default_factory=list)  # field names rendered


@dataclass
class RouteIR:
    """URL route → view mapping."""
    path: str
    view_name: str
    method: str = 'GET'


@dataclass
class StateIR:
    """Something that must persist between requests."""
    name: str
    type: str           # 'session', 'db', 'cookie', 'global'
    model: str = ''     # which ModelIR it belongs to


@dataclass
class AppIR:
    """The complete intermediate representation of one app."""
    name: str
    models: list = field(default_factory=list)   # list of ModelIR
    views: list = field(default_factory=list)     # list of ViewIR
    routes: list = field(default_factory=list)    # list of RouteIR
    state: list = field(default_factory=list)     # list of StateIR

    @property
    def total_storage(self):
        return sum(m.storage_bytes for m in self.models)

    @property
    def summary(self):
        return (f'{self.name}: {len(self.models)} models, '
                f'{len(self.views)} views, {len(self.routes)} routes, '
                f'~{self.total_storage} bytes state')

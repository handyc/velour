"""Tier capability profiles — what each tier can "prove" (implement).

Inspired by Gödel: a formal system can only prove statements within
its expressive power. An ATTiny can't prove "paginated list" any more
than Peano arithmetic can prove its own consistency. The Condenser
identifies which IR operations are provable at each tier and
automatically sheds the rest.

Inspired by Wang tiles: the IR is the tileset, each tier is a
constraint system, and the generator finds which IR elements "tile"
(fit) at that tier. The condensation is a matching operation.
"""

from dataclasses import dataclass, field


@dataclass
class TierCapability:
    """What a tier can do."""
    name: str
    max_models: int             # how many distinct data types
    max_fields_per_model: int   # fields per type
    max_records: int            # total data rows/instances
    max_string_length: int      # longest string
    supports_persistence: bool  # data survives power cycle
    supports_dynamic_ui: bool   # can change what's displayed
    supports_user_input: bool   # can accept input
    supports_network: bool      # can talk to other devices
    supports_multiple_views: bool  # more than one "page"
    supports_crud: set = field(default_factory=set)  # which CRUD ops
    max_code_bytes: int = 0     # code size limit
    max_ram_bytes: int = 0      # runtime memory
    output_extension: str = 'txt'


# Define what each tier can prove
TIERS = {
    'js': TierCapability(
        name='JS (browser)',
        max_models=99,
        max_fields_per_model=99,
        max_records=10000,
        max_string_length=10000,
        supports_persistence=True,   # localStorage
        supports_dynamic_ui=True,
        supports_user_input=True,
        supports_network=False,      # no server to talk to
        supports_multiple_views=True,
        supports_crud={'create', 'read', 'update', 'delete', 'list'},
        max_code_bytes=100000,
        max_ram_bytes=50000000,      # browser has plenty
        output_extension='html',
    ),
    'esp': TierCapability(
        name='ESP8266',
        max_models=10,
        max_fields_per_model=20,
        max_records=100,             # PROGMEM is limited
        max_string_length=200,
        supports_persistence=True,   # PROGMEM + EEPROM
        supports_dynamic_ui=True,    # serves HTML
        supports_user_input=True,    # HTTP POST
        supports_network=True,       # WiFi
        supports_multiple_views=True,
        supports_crud={'create', 'read', 'update', 'delete', 'list'},
        max_code_bytes=800000,       # ~800KB flash
        max_ram_bytes=40000,         # ~40KB heap
        output_extension='ino',
    ),
    'attiny': TierCapability(
        name='ATTiny13a',
        max_models=2,
        max_fields_per_model=4,
        max_records=8,               # lookup table entries
        max_string_length=0,         # no strings
        supports_persistence=True,   # EEPROM (64 bytes)
        supports_dynamic_ui=False,   # no display
        supports_user_input=True,    # pin reads
        supports_network=False,
        supports_multiple_views=False,
        supports_crud={'read'},      # can only read from lookup
        max_code_bytes=1024,
        max_ram_bytes=64,
        output_extension='c',
    ),
    'circuit': TierCapability(
        name='555 timers',
        max_models=1,
        max_fields_per_model=2,      # two voltage levels
        max_records=4,               # 4 entries in truth table
        max_string_length=0,
        supports_persistence=True,   # capacitor holds charge
        supports_dynamic_ui=False,
        supports_user_input=True,    # potentiometer/switch
        supports_network=False,
        supports_multiple_views=False,
        supports_crud={'read'},
        max_code_bytes=0,            # no code
        max_ram_bytes=0,
        output_extension='txt',
    ),
}


def filter_ir_for_tier(ir, tier_name):
    """Filter an AppIR to only include what's provable at this tier.

    This is the Gödel step: shed everything the tier can't express.
    Returns a new AppIR with only the surviving elements.
    """
    from .ir import AppIR, ModelIR, FieldIR, ViewIR, RouteIR, StateIR

    cap = TIERS.get(tier_name)
    if not cap:
        return ir

    new_ir = AppIR(name=ir.name)

    # Filter models: keep only what fits
    for i, model in enumerate(ir.models):
        if i >= cap.max_models:
            break
        new_model = ModelIR(name=model.name)
        for j, f in enumerate(model.fields):
            if j >= cap.max_fields_per_model:
                break
            # Skip string fields if tier can't handle strings
            if f.type == 'str' and cap.max_string_length == 0:
                # Downgrade to int (hash or enum index)
                new_f = FieldIR(name=f.name, type='int',
                                choices=f.choices, default=0)
            elif f.type == 'str' and f.max_length > cap.max_string_length:
                new_f = FieldIR(name=f.name, type='str',
                                max_length=cap.max_string_length)
            elif f.type == 'json':
                if cap.max_string_length > 0:
                    new_f = FieldIR(name=f.name, type='str',
                                    max_length=cap.max_string_length)
                else:
                    continue  # can't represent JSON at this tier
            else:
                new_f = FieldIR(name=f.name, type=f.type,
                                default=f.default,
                                max_length=min(f.max_length, cap.max_string_length),
                                choices=f.choices)
            new_model.fields.append(new_f)
        if new_model.fields:
            new_ir.models.append(new_model)

    # Filter views: keep only those with provable operations
    for view in ir.views:
        # Check if all steps are provable at this tier
        provable = True
        new_steps = []
        for step in view.steps:
            if step.op == 'render' and not cap.supports_dynamic_ui:
                # Can't render UI — convert to "output" (pin state)
                from .ir import LogicStep
                new_steps.append(LogicStep(op='output', target=step.target))
            elif step.op == 'write' and 'create' not in cap.supports_crud:
                provable = False
                break
            elif step.op == 'read' and 'read' not in cap.supports_crud:
                provable = False
                break
            elif step.op == 'redirect' and not cap.supports_multiple_views:
                continue  # silently drop redirects
            else:
                new_steps.append(step)

        if provable and new_steps:
            new_view = ViewIR(name=view.name, method=view.method,
                              steps=new_steps)
            new_ir.views.append(new_view)

    # Filter routes
    surviving_views = {v.name for v in new_ir.views}
    for route in ir.routes:
        if route.view_name in surviving_views:
            if cap.supports_multiple_views or len(new_ir.routes) == 0:
                new_ir.routes.append(route)

    return new_ir

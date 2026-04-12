"""Tier 5 generator: AppIR → 555 timer circuit description.

At this tier, program/state/hardware merge into one thing.
The IR's models become voltage levels on capacitors.
The IR's logic becomes comparator networks.
The IR's routes become wire topology.

Each model field that survived to this tier (max 2 per model,
max 1 model) becomes a voltage level in an RC network.
"""

from .capabilities import filter_ir_for_tier


def generate(ir):
    """Generate a 555 circuit description from an AppIR."""
    fir = filter_ir_for_tier(ir, 'circuit')

    lines = []
    lines.append(f'// Condenser: {ir.name} → 555 timer circuit')
    lines.append(f'//')
    lines.append(f'// Original: {len(ir.models)} models, {len(ir.views)} views')
    lines.append(f'// Reduced:  {len(fir.models)} models, {len(fir.views)} views')
    lines.append(f'// State:    {fir.total_storage} bytes → {fir.total_storage} voltage levels')
    lines.append(f'//')
    lines.append(f'// At this tier, the code IS the circuit IS the data.')
    lines.append(f'// There is nothing to compile. There is nothing to run.')
    lines.append(f'// The circuit EXISTS and that is enough.')
    lines.append('')

    # Clock
    lines.append('// CLOCK: NE555 astable')
    lines.append('//   R1 = 22kΩ, R2 = 27kΩ, C = 10µF')
    lines.append('//   Period ≈ 527ms (1.9 Hz)')
    lines.append('//   This is the "tick rate" — how fast the circuit thinks.')
    lines.append('')

    # Each surviving model field becomes a voltage level
    for model in fir.models:
        lines.append(f'// STATE: {model.name}')
        for f in model.fields:
            if f.type == 'int':
                lines.append(f'//   {f.name}: stored as capacitor charge on C_{f.name}')
                lines.append(f'//     LOW = 0V (discharged), HIGH = VCC (charged)')
                lines.append(f'//     Read via comparator: LM393 + Vref = VCC/2')
            elif f.type == 'bool':
                lines.append(f'//   {f.name}: stored as flip-flop state (555 bistable)')
                lines.append(f'//     SET = VCC, RESET = 0V')
        lines.append('')

    # Each view becomes a section of the circuit
    for view in fir.views:
        lines.append(f'// LOGIC: {view.name}')
        for step in view.steps:
            if step.op == 'read':
                lines.append(f'//   Read {step.target}: wire from C_{step.target} to comparator input')
            elif step.op == 'output':
                lines.append(f'//   Output: comparator drives transistor → LED')
        lines.append('')

    # BOM
    n_models = len(fir.models)
    n_fields = sum(len(m.fields) for m in fir.models)
    n_555 = 1  # clock
    n_comp = max(n_fields, 1)
    n_res = 4 + n_fields * 2
    n_cap = 1 + n_fields
    n_led = max(n_fields, 1)
    cost = n_555 * 0.30 + n_comp * 0.25 + n_res * 0.02 + n_cap * 0.05 + n_led * 0.05

    lines.append('// BILL OF MATERIALS:')
    lines.append(f'//   {n_555}× NE555')
    lines.append(f'//   {n_comp}× LM393 comparator')
    lines.append(f'//   {n_res}× resistors')
    lines.append(f'//   {n_cap}× capacitors')
    lines.append(f'//   {n_led}× LEDs')
    lines.append(f'//   Total: ${cost:.2f}')
    lines.append('')
    lines.append(f'// The app "{ir.name}" began as {len(ir.models)} models and')
    lines.append(f'// {len(ir.views)} views in Django. It is now ${cost:.2f}')
    lines.append(f'// of discrete components. The logic is preserved.')
    lines.append(f'// The meaning is in the observer.')

    return '\n'.join(lines)

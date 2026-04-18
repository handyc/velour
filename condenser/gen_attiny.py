"""Tier 4 generator: AppIR → ATTiny13a C code.

The insight: at ATTiny level, every model becomes a lookup table,
every view becomes a step in the main loop, every route becomes
a pin read. The IR's state is the chip's SRAM. The IR's logic
is the chip's instruction sequence.

GPIO pins ARE the database:
  - Reading a pin IS a SELECT query
  - Setting a pin IS an INSERT/UPDATE
  - The pin state IS the current row

This generator produces compilable avr-gcc C code.
"""

from .capabilities import filter_ir_for_tier


def generate(ir):
    """Generate ATTiny13a C code from an AppIR."""
    fir = filter_ir_for_tier(ir, 'attiny')

    lines = []
    lines.append(f'// Condenser: {ir.name} → ATTiny13a')
    lines.append(f'// Reduced from {len(ir.models)} models to {len(fir.models)} models')
    lines.append(f'// State: {fir.total_storage} bytes (of 64B SRAM)')
    lines.append('//')
    lines.append('// GPIO pins ARE the database.')
    lines.append('// Reading a pin IS a query. Setting a pin IS a write.')
    lines.append('')
    lines.append('#include <avr/io.h>')
    lines.append('#include <util/delay.h>')
    lines.append('')

    # Generate lookup tables from models
    for model in fir.models:
        lines.append(f'// Model: {model.name}')
        lines.append(f'// Fields: {", ".join(f.name for f in model.fields)}')

        # For models with integer fields, generate a compact struct
        int_fields = [f for f in model.fields if f.type in ('int', 'bool')]
        if int_fields:
            lines.append(f'typedef struct {{')
            for f in int_fields[:4]:  # max 4 fields per struct at ATTiny
                lines.append(f'    uint8_t {f.name};')
            lines.append(f'}} {model.name}_t;')
            lines.append('')

    # Pin assignments
    lines.append('// Pin assignments (2 inputs, 2 outputs, 1 LED)')
    lines.append('#define PIN_IN0  PB0   // input 0')
    lines.append('#define PIN_IN1  PB1   // input 1')
    lines.append('#define PIN_OUT0 PB2   // output 0')
    lines.append('#define PIN_OUT1 PB3   // output 1')
    lines.append('#define PIN_LED  PB4   // status')
    lines.append('')

    # Main loop — read inputs, process, write outputs
    lines.append('int main(void) {')
    lines.append('    // Pin directions')
    lines.append('    DDRB = (1 << PIN_OUT0) | (1 << PIN_OUT1) | (1 << PIN_LED);')
    lines.append('    PORTB = (1 << PIN_IN0) | (1 << PIN_IN1); // pull-ups')
    lines.append('')
    lines.append('    while (1) {')
    lines.append('        // READ: query the pin database')
    lines.append('        uint8_t in0 = (PINB >> PIN_IN0) & 1;')
    lines.append('        uint8_t in1 = (PINB >> PIN_IN1) & 1;')
    lines.append('        // Default pass-through; each view may override below.')
    lines.append('        uint8_t out0 = in0;')
    lines.append('        uint8_t out1 = in1;')
    lines.append('')

    # Generate logic from views. out0/out1 are declared once above; each
    # view's output step reassigns them so multiple views don't fight the
    # C "redefinition" rule.
    for view in fir.views:
        lines.append(f'        // View: {view.name}')
        for step in view.steps:
            if step.op == 'read':
                lines.append(f'        // read {step.target} → pins already read above')
            elif step.op == 'output':
                lines.append(f'        // output: set pins based on state')
                lines.append(f'        out0 = in0;  // pass-through (customize)')
                lines.append(f'        out1 = in1;')
            elif step.op == 'compute':
                lines.append(f'        // compute: transform input to output')
        lines.append('')

    lines.append('        // WRITE: update output pins')
    lines.append('        if (out0) PORTB |= (1 << PIN_OUT0);')
    lines.append('        else PORTB &= ~(1 << PIN_OUT0);')
    lines.append('        if (out1) PORTB |= (1 << PIN_OUT1);')
    lines.append('        else PORTB &= ~(1 << PIN_OUT1);')
    lines.append('')
    lines.append('        // Heartbeat')
    lines.append('        PORTB ^= (1 << PIN_LED);')
    lines.append('        _delay_ms(100);')
    lines.append('    }')
    lines.append('    return 0;')
    lines.append('}')

    return '\n'.join(lines)

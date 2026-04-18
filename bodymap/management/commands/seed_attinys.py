"""Seed the ATtiny workshop with its starter template library.

Upsert on slug so the command is idempotent — editing an existing
template's metadata or source and re-running picks up the change.
Does not touch AttinyDesign rows (user-authored derivatives).
"""

from pathlib import Path

from django.core.management.base import BaseCommand

from bodymap.models import AttinyTemplate


TEMPLATES = [
    # (slug, name, mcu, summary, pinout, description)
    ('blink_pwm', 'Blink / PWM', 'attiny85',
     'Simplest template — pot fades an LED via PWM.',
     'PB0 = PWM output, PB2 = pot (ADC1).',
     'Use as a sanity check that ADC + Timer0 + your soldering are '
     'all working. No filter, no memory — just raw pot to PWM duty.'),

    ('threshold_gate', 'Threshold gate', 'attiny85',
     'Hysteresis comparator — signal crosses a pot threshold, output goes high.',
     'PB0 = gate out, PB1 = transition LED, PB2 = threshold pot, PB3 = signal in.',
     'Classic open-loop comparator with 2-bit hysteresis. Good for '
     'tap/knock detectors, piezo triggers, photocell tripwires. Tweak '
     'HYST_BITS in-source if the gate chatters on your signal.'),

    ('envelope_follower', 'Envelope follower', 'attiny85',
     'One-pole exponential smoothing of an analog input → PWM envelope.',
     'PB0 = PWM envelope, PB2 = decay pot, PB3 = signal in.',
     'Standard audio/vibration amplitude follower. Rectifies the input '
     'around the midrail and runs a lowpass with pot-controlled time '
     'constant. Right knob = slow and legato, left knob = snappy.'),

    ('vco_square', 'Square wave VCO', 'attiny85',
     'Audio-rate square wave with pot-controlled frequency and duty.',
     'PB0 = square out, PB2 = freq pot, PB4 = duty pot.',
     'Busy-wait oscillator (Timer0 kept free for duty-PWM use cases). '
     'Covers roughly 50 Hz – 8 kHz. Feed into a piezo for audio, or '
     'into an ESP ADC pin as a known-frequency test signal.'),

    ('peak_hold', 'Peak hold', 'attiny85',
     'Max-value detector with pot-controlled decay rate.',
     'PB0 = PWM output, PB2 = decay pot, PB3 = signal in.',
     'Latches the highest recent reading and decays it slowly. '
     'Turns transient events (taps, snaps, footfall) into sustained '
     'levels a slower downstream reader can see.'),

    ('i2c_slave_skeleton', 'I2C slave skeleton', 'attiny85',
     'USI-based I2C slave exposing a single 16-bit register — the bodymap-mesh contract.',
     'PB0 = SDA, PB2 = SCL, PB3 = signal in (ADC3), PB4 = param pot (ADC2), PB1 free.',
     'Copy of the wire contract every bodymap coprocessor follows: ESP '
     'reads two bytes (hi, lo) from the slave address each tick. The '
     'USI+ISR plumbing is boilerplate — scroll to the USER TRANSFORM '
     'block in main() and only edit there.'),

    # --- ATtiny13a variants -------------------------------------------------
    # The '13a has 1 KB flash, 64 B RAM, no USI peripheral. The bodymap
    # coprocessor pattern for the '13a is "PWM out → ESP ADC in" per
    # tiny, not I2C — the ESP32-S3 has plenty of ADC pins and a bit-
    # banged I2C slave would eat nearly half the flash budget.
    ('blink_pwm_13a', 'Blink / PWM (13a)', 'attiny13a',
     'Blink / PWM starter, squeezed into the 1 KB flash of the \'13a.',
     'PB0 = PWM output, PB2 = pot (ADC1).',
     'Same behavior as blink_pwm but targets ATtiny13a. Runs at '
     '1.2 MHz out of the box (CKDIV8 fuse active); clear the fuse if '
     'you want 9.6 MHz.'),

    ('threshold_gate_13a', 'Threshold gate (13a)', 'attiny13a',
     'Hysteresis comparator — \'13a version of threshold_gate.',
     'PB0 = gate out, PB1 = transition LED, PB2 = threshold pot, PB3 = signal in.',
     'Same pinout as the \'85 version so layouts port straight across. '
     'Compiles to <300 bytes.'),

    ('envelope_follower_13a', 'Envelope follower (13a)', 'attiny13a',
     'Q8 one-pole lowpass — \'13a-sized envelope follower.',
     'PB0 = PWM envelope, PB2 = decay pot, PB3 = signal in.',
     'Q8 math instead of the \'85 template\'s Q16 (keeps RAM under the '
     '64 B ceiling). ~1% envelope precision, fine for LEDs and slow '
     'actuators.'),

    ('vco_square_13a', 'Square wave VCO (13a)', 'attiny13a',
     'Pot-controlled square wave, ~50 Hz – 2 kHz range.',
     'PB0 = square out, PB2 = freq pot, PB4 = duty pot.',
     'Busy-wait oscillator. The 1.2 MHz clock limits range vs the '
     '\'85\'s 8 MHz — plenty for piezos and tachometer references.'),

    ('peak_hold_13a', 'Peak hold (13a)', 'attiny13a',
     'Max detector with pot-controlled decay, \'13a edition.',
     'PB0 = PWM output, PB2 = decay pot, PB3 = signal in.',
     'Sustains a brief event (tap, snap) at its peak level so a '
     'slower reader can catch it.'),

    ('gpio_test_13a', 'GPIO test (13a)', 'attiny13a',
     'Bring-up sanity check: LED chase, pot-controlled brightness, reset-button greeter.',
     'PB0 = brightness LED (PWM), PB1/PB3/PB4 = chase LEDs, PB2 = pot, PB5 = RESET/button.',
     'Solder one LED to each of PB0, PB1, PB3, PB4 and a pot on PB2 '
     'to verify every GPIO works on a freshly socketed chip. Pressing '
     'the reset button (a switch from PB5 to GND) triggers a 3-blink '
     '\'hello\' before the normal chase resumes — proves the external '
     'reset path is intact. The MCUSR EXTRF bit is latched + cleared '
     'at boot so the greeting only plays on an actual button press.'),

    ('lut_filter_13a', 'Two-input LUT filter (13a)', 'attiny13a',
     '16 boolean truth tables in one chip — pot picks AND / OR / XOR / NAND / etc.',
     'PB0 = C out, PB1 = LUT indicator (PWM), PB2 = LUT pot (ADC1), PB3 = A in, PB4 = B in.',
     'A and B are digital inputs, C is the chosen boolean function of '
     'them. The pot selects one of all 16 possible 2-input boolean '
     'operations — the LUT *index* is literally its truth table, so '
     'C = bit((A<<1)|B) of the index. PB1 fades from dim→bright as '
     'you sweep through the tables, a poor-man\'s \'which function '
     'am I\' display. Handy as a reconfigurable glue-logic building '
     'block for the bodymap mesh.'),

    ('lut_fb_13a', 'LUT filter + feedback (13a)', 'attiny13a',
     '256 tiny state machines in one chip — pot sweeps them, A-input XORs with last cycle\'s carry.',
     'PB0 = C out, PB1 = carry / feedback LED, PB2 = LUT pot (ADC1), PB3 = A in, PB4 = B in.',
     'Like lut_filter_13a but each LUT entry now emits TWO bits — the '
     'C output (to PB0) and a "carry" bit that is latched and XORed '
     'into the A input on the next ~20 Hz tick. That adds one bit of '
     'internal state, which turns every LUT index into a small '
     'sequential cell: some behave as latches, some oscillate, some '
     'wait for B before advancing. 256 LUTs on one pot — a very dense '
     'exploration space for reconfigurable glue logic.'),

    ('ca_rule_13a', 'Cellular automaton rule (13a)', 'attiny13a',
     'Wolfram-style 3→1 elementary CA cell — pot picks one of 256 rules (Rule 30, 90, 110, …).',
     'PB0 = C_new out, PB1 = L in, PB2 = rule pot (ADC1), PB3 = C in, PB4 = R in.',
     'Purely combinational 3-input lookup: for neighborhood (L,C,R) '
     'the output is bit((L<<2)|(C<<1)|R) of the selected rule index. '
     'The pot sweeps all 256 Wolfram rules. Chain N of these chips — '
     'wire each one\'s PB0 into the next one\'s R and the previous '
     'one\'s L into PB1 — plus an external clock to latch cell state, '
     'and you have a 1D cellular automaton in hardware. Inputs use '
     'internal pull-ups + active-low convention so an unconnected '
     'neighbor reads 0.'),
]


class Command(BaseCommand):
    help = 'Seed / refresh the ATtiny workshop starter templates.'

    def handle(self, *args, **opts):
        src_dir = Path(__file__).resolve().parent.parent.parent / 'attiny_sources'
        created = 0
        updated = 0

        for slug, name, mcu, summary, pinout, description in TEMPLATES:
            source_path = src_dir / f'{slug}.c'
            if not source_path.is_file():
                self.stderr.write(f'  skip {slug}: missing {source_path}')
                continue
            c_source = source_path.read_text()

            obj, was_created = AttinyTemplate.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':        name,
                    'mcu':         mcu,
                    'summary':     summary,
                    'pinout':      pinout,
                    'description': description,
                    'c_source':    c_source,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f'  +  {slug}  ({name})')
            else:
                updated += 1
                self.stdout.write(f'  ~  {slug}  ({name})')

        self.stdout.write(
            self.style.SUCCESS(
                f'Attiny templates: {created} created, {updated} updated.'
            )
        )

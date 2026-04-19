"""Seed the Power Lab with the solar → supercap charge-pump design
and the parts it needs.

Idempotent — upserts by slug. Safe to re-run after edits.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand

from powerlab.models import Circuit, CircuitPart, Part, PartPriceSnapshot


PARTS = [
    # slug                          category     name                                   mpn            price   specs
    ('schottky-1n5819',             'schottky',  '1N5819 Schottky rectifier (DO-41)',   '1N5819',      0.08,
     {'vf_mv': 340, 'if_a': 1.0, 'vr_v': 40}),
    ('schottky-bat54',              'schottky',  'BAT54 dual Schottky (SOT-23)',        'BAT54',       0.06,
     {'vf_mv': 320, 'if_ma': 200, 'vr_v': 30}),
    ('comparator-tlv3691',          'comparator','TLV3691 nanopower comparator',        'TLV3691IDCKR', 0.90,
     {'iq_na': 150, 'vsupply_v': '0.9-6.5'}),
    ('voltage-ref-tl431',           'ic',        'TL431 shunt voltage reference',       'TL431',       0.07,
     {'vref_v': 2.495}),
    ('mosfet-dmp2100l',             'mosfet',    'DMP2100L P-channel MOSFET (SOT-23)',  'DMP2100L',    0.25,
     {'vgs_th_v': -1.0, 'rds_on_mohm': 40, 'id_a': 2.7, 'polarity': 'p'}),
    ('ldo-mcp1700-3302',            'regulator', 'MCP1700-3302E 3.3V LDO',              'MCP1700-3302E/TO', 0.35,
     {'vout_v': 3.3, 'iq_ua': 1.6, 'iout_ma': 250}),
    ('cap-47uf-ceramic',            'capacitor', '47µF 25V ceramic (1210)',             '',            0.12,
     {'c_uf': 47, 'v_rating_v': 25, 'dielectric': 'X5R'}),
    ('cap-100uf-electrolytic',      'capacitor', '100µF 25V electrolytic',              '',            0.08,
     {'c_uf': 100, 'v_rating_v': 25}),
    ('supercap-1f-5v5',             'supercap',  '1F 5.5V supercapacitor',              '',            0.85,
     {'c_f': 1.0, 'v_rating_v': 5.5, 'esr_ohm': 1.5}),
    ('supercap-5f-2v7-pair',        'supercap',  '5F 2.7V supercap (pair for 5V4 stack)', '',          1.80,
     {'c_f': 5.0, 'v_rating_v': 2.7, 'note': 'two in series gives 2.5F @ 5.4V'}),
    ('zener-5v1',                   'zener',     '5.1V zener diode (BZX55)',            'BZX55C5V1',   0.04,
     {'vz_v': 5.1, 'pd_mw': 500}),
    ('resistor-1m',                 'resistor',  '1MΩ 1% metal film 1/4W',              '',            0.02,
     {'r_ohm': 1_000_000, 'tol_pct': 1}),
    ('resistor-100k',               'resistor',  '100kΩ 1% metal film 1/4W',            '',            0.02,
     {'r_ohm': 100_000, 'tol_pct': 1}),
    ('resistor-330k',               'resistor',  '330kΩ 1% metal film 1/4W',            '',            0.02,
     {'r_ohm': 330_000, 'tol_pct': 1}),
    ('solar-panel-6v-100ma',        'panel',     '6V 100mA 0.6W solar panel (60x60mm)', '',            2.40,
     {'voc_v': 6.5, 'isc_ma': 120, 'vmp_v': 5.5, 'imp_ma': 110}),
    ('solar-panel-12v-200ma',       'panel',     '12V 200mA 2.4W solar panel',          '',            6.50,
     {'voc_v': 14.5, 'isc_ma': 220, 'vmp_v': 12, 'imp_ma': 200}),
    ('attiny13a',                   'mcu',       'ATtiny13A 8-bit MCU (DIP-8)',         'ATTINY13A-PU', 0.80,
     {'flash_kb': 1, 'sram_b': 64, 'v_min': 1.8, 'iq_sleep_ua': 2}),
    ('attiny85',                    'mcu',       'ATtiny85-20PU (DIP-8)',               'ATTINY85-20PU', 1.50,
     {'flash_kb': 8, 'sram_b': 512, 'v_min': 2.7}),
    ('esp32s3-supermini',           'mcu',       'ESP32-S3 SuperMini dev board',        '',            3.50,
     {'flash_mb': 4, 'v_operating': 3.3, 'wifi': True, 'ble': True}),
]


SOLAR_PUMP_BODY = """\
The idea: a normal 12V solar panel makes more voltage than an ATtiny
or ESP needs, but under load its voltage collapses at low light — often
below what a linear regulator can use. So instead of drawing
continuously, we *pump*:

1. The panel charges a small reservoir cap (C1) through a Schottky (D1).
   The Schottky prevents reverse flow when the panel sags.
2. A nanopower hysteretic comparator (U1) watches C1. When it rises to
   ~4.5V the comparator pulls Q1's gate low, turning on the P-MOSFET.
3. Q1 dumps C1's charge through a second Schottky (D2) into a 1F
   supercap (C2). D2 stops C2 from draining backwards into Q1 when C1
   is low.
4. When C1 drops to ~3.0V the comparator opens Q1 and the cycle
   repeats.
5. C2 feeds a low-Iq LDO (U2) that powers the load (ATtiny / ESP-S3)
   at 3.3V.

The panel therefore sees a light, intermittent load (a ~47µF cap
charging up), and is free to climb to a high voltage before each dump.
The hysteretic threshold protects against low-light dithering.

**Two-supercap tip:** instead of one 5.5V 1F cap, use two 2.7V 5F caps
in series with balancing resistors. This gives ~2.5F at 5.4V — deeper
storage and still within a safe voltage window.

**Where to evolve this:** the parameter space (reservoir cap size,
comparator thresholds, MOSFET, supercap size, panel size) is naturally
evolvable. Fitness = uptime per lux-hour. This is the seed topology
for later Evolution-Engine-driven search.
"""

SOLAR_PUMP_DIAGRAM = """\
   solar panel                                          supercap
   Voc 12V .----.         reservoir             dump    1F / 5.5V
           |    |    D1      C1                  D2       C2
     +-----o    o---|>|---+----||----+        ---|>|---+---||---+-----+
     |     |    |         |          |       |         |        |     |
     |     '----'       +---+   +----+----+  |         |    .---+-----+---.
     |       PV         | U1| ->|   Q1    |--'         +----| U2 LDO 3.3V |
     |                  |cmp| G |P-MOSFET |                 '------+------+
     |     5k           +---+   +----+----+                        |
     |     / R_div                    |                            |  3.3V
     |     \\                          |                           +---> ATtiny
     |     /                           |                           |     / ESP
     |     \\                          |                           |
     +-----+---------------------------+--------------------------+
                              GND  ---------------------------
"""


CIRCUIT = {
    'slug': 'solar-pump-supercap-v1',
    'title': 'Solar → Supercap Charge Pump v1',
    'tagline': (
        'Hysteretic bucket-brigade harvester: 12V panel pumps a small '
        'reservoir that periodically dumps into a 1F supercap, feeding a '
        'low-Iq LDO.'
    ),
    'status':       Circuit.STATUS_DRAFT,
    'body_md':      SOLAR_PUMP_BODY,
    'diagram_kind': 'svgbob',
    'diagram_source': SOLAR_PUMP_DIAGRAM,
    'display_order': 10,
}


BOM = [
    # designator, part_slug, qty, notes
    ('PV1', 'solar-panel-12v-200ma', 1, '~2.4W panel; 6V option also works'),
    ('D1',  'schottky-1n5819',       1, 'panel → reservoir; low Vf matters'),
    ('D2',  'schottky-1n5819',       1, 'reservoir → supercap dump path'),
    ('C1',  'cap-47uf-ceramic',      1, 'reservoir — charges during light gusts'),
    ('C2',  'supercap-1f-5v5',       1, 'main storage; swap for 5F×2 for more depth'),
    ('U1',  'comparator-tlv3691',    1, 'hysteretic switch, 150nA Iq'),
    ('Q1',  'mosfet-dmp2100l',       1, 'P-channel dump switch'),
    ('U2',  'ldo-mcp1700-3302',      1, '3.3V out, 1.6µA Iq'),
    ('R1',  'resistor-1m',           1, 'U1 upper threshold divider'),
    ('R2',  'resistor-330k',         1, 'U1 lower threshold divider'),
    ('R3',  'resistor-100k',         1, 'Q1 gate pull-up'),
    ('D3',  'zener-5v1',             1, 'supercap over-voltage clamp (belt-and-braces)'),
]


class Command(BaseCommand):
    help = "Seed the Power Lab with the solar → supercap charge-pump and its parts."

    def handle(self, *args, **opts):
        # Parts
        parts_by_slug = {}
        for slug, cat, name, mpn, price, specs in PARTS:
            part, created = Part.objects.update_or_create(
                slug=slug,
                defaults={
                    'name':     name,
                    'mpn':      mpn,
                    'category': cat,
                    'specs':    specs,
                },
            )
            parts_by_slug[slug] = part

            # Seed one "estimated" vendor snapshot if none exist yet.
            if not part.price_snapshots.exists():
                PartPriceSnapshot.objects.create(
                    part=part,
                    vendor='estimate',
                    unit_price_usd=Decimal(str(price)),
                    qty_break=1,
                    source_url='',
                )
            part.recompute_avg_price()

            action = 'created' if created else 'updated'
            self.stdout.write(f"  [{action}] part {slug}  ${price:.2f}")

        # Circuit
        circ, created = Circuit.objects.update_or_create(
            slug=CIRCUIT['slug'],
            defaults={k: v for k, v in CIRCUIT.items() if k != 'slug'},
        )
        action = 'created' if created else 'updated'
        self.stdout.write(f"  [{action}] circuit {circ.slug}")

        # BOM — wipe and rewrite (idempotent)
        circ.bom.all().delete()
        for i, (des, part_slug, qty, notes) in enumerate(BOM):
            CircuitPart.objects.create(
                circuit=circ,
                part=parts_by_slug[part_slug],
                designator=des,
                qty=qty,
                notes=notes,
                display_order=(i + 1) * 10,
            )
        self.stdout.write(f"  [wrote] {len(BOM)} BOM lines  →  ${circ.bom_total_usd}")
        self.stdout.write(self.style.SUCCESS("powerlab seed complete"))

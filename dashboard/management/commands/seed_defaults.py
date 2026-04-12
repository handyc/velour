"""Seed a fresh Velour database with sensible defaults.

Run after `migrate` on a new install or after a DB reset:

    python manage.py seed_defaults

Idempotent — safe to run multiple times. Uses get_or_create for
everything so existing data is not overwritten.
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Seed the database with default Identity, Chronos, Fleet, and Tiles data.'

    def handle(self, *args, **options):
        self._seed_identity()
        self._seed_chronos()
        self._seed_fleet()
        self._seed_tiles()
        self.stdout.write(self.style.SUCCESS('Done.'))

    def _seed_identity(self):
        from identity.models import Identity, IdentityToggles
        identity = Identity.get_self()
        self.stdout.write(f'  Identity: {identity.name} (mood={identity.mood})')
        toggles = IdentityToggles.get_self()
        self.stdout.write(f'  Toggles: tile slider={toggles.tile_generation_slider}')

    def _seed_chronos(self):
        from chronos.models import ClockPrefs, WatchedTimezone

        ClockPrefs.load()
        self.stdout.write('  ClockPrefs: loaded')

        cities = [
            ('Pacific/Midway',       'Midway',         -1100),
            ('Pacific/Honolulu',     'Honolulu',       -1000),
            ('Pacific/Marquesas',    'Marquesas',       -950),
            ('America/Anchorage',    'Anchorage',       -900),
            ('America/Los_Angeles',  'Los Angeles',     -800),
            ('America/Denver',       'Denver',          -700),
            ('America/Chicago',      'Chicago',         -600),
            ('America/New_York',     'New York',        -500),
            ('America/Caracas',      'Caracas',         -400),
            ('America/St_Johns',     "St. John's",      -350),
            ('America/Sao_Paulo',    'São Paulo',       -300),
            ('Atlantic/South_Georgia', 'S. Georgia',    -200),
            ('Atlantic/Azores',      'Azores',          -100),
            ('Europe/London',        'London',             0),
            ('Europe/Amsterdam',     'Leiden',           100),
            ('Europe/Athens',        'Athens',            200),
            ('Europe/Moscow',        'Moscow',            300),
            ('Asia/Tehran',          'Tehran',            350),
            ('Asia/Dubai',           'Dubai',             400),
            ('Asia/Kabul',           'Kabul',             450),
            ('Asia/Karachi',         'Karachi',           500),
            ('Asia/Kolkata',         'Mumbai',            550),
            ('Asia/Kathmandu',       'Kathmandu',         575),
            ('Asia/Dhaka',           'Dhaka',             600),
            ('Asia/Yangon',          'Yangon',            650),
            ('Asia/Bangkok',         'Bangkok',           700),
            ('Asia/Shanghai',        'Shanghai',          800),
            ('Australia/Eucla',      'Eucla',             875),
            ('Asia/Tokyo',           'Tokyo',             900),
            ('Australia/Darwin',     'Darwin',            950),
            ('Australia/Sydney',     'Sydney',           1000),
            ('Australia/Lord_Howe',  'Lord Howe',        1050),
            ('Pacific/Noumea',       'Nouméa',           1100),
            ('Pacific/Auckland',     'Auckland',         1200),
            ('Pacific/Chatham',      'Chatham Is.',      1275),
            ('Pacific/Tongatapu',    'Tonga',            1300),
            ('Pacific/Kiritimati',   'Kiritimati',       1400),
        ]
        created = 0
        for tz, label, sort in cities:
            _, c = WatchedTimezone.objects.get_or_create(
                tz_name=tz, defaults={'label': label, 'sort_order': sort})
            if c:
                created += 1
        self.stdout.write(f'  Chronos: {created} new clocks, {len(cities)} total')

    def _seed_fleet(self):
        from nodes.models import Node, HardwareProfile

        hp_nodemcu, _ = HardwareProfile.objects.get_or_create(
            name='ESP8266 NodeMCU',
            defaults={'mcu': 'esp8266', 'flash_mb': 4, 'ram_kb': 80,
                      'has_wifi': True})
        hp_nodemcu_oled, _ = HardwareProfile.objects.get_or_create(
            name='ESP8266 NodeMCU + OLED',
            defaults={'mcu': 'esp8266', 'flash_mb': 4, 'ram_kb': 80,
                      'has_wifi': True,
                      'notes': 'SSD1306 128x64 OLED on SW I2C (SCL=14, SDA=12).'})
        hp_ttgo, _ = HardwareProfile.objects.get_or_create(
            name='TTGO T3 V1.6.1 (ESP32 + LoRa + OLED)',
            defaults={'mcu': 'esp32', 'flash_mb': 4, 'ram_kb': 520,
                      'has_wifi': True, 'has_bluetooth': True, 'has_lora': True,
                      'notes': 'ESP32-PICO-D4, SX1276 LoRa, SSD1306 128x64 OLED on HW I2C.'})

        nodes = [
            ('gary',  'Gary',  hp_nodemcu,      '5F3Y4IH3qVqrF1O2SCGFaxdY5BICckTkfz6MT6gSDXzOgSO6'),
            ('larry', 'Larry', hp_nodemcu,      'B0dcZG6lUbc4ywEPshrmyC5RaylzzYPjVTVxBLxTmfGXygQF'),
            ('terry', 'Terry', hp_nodemcu_oled, 'zbajrfg2ifkKSLS8n2Hn0WwuaEmrA1Cgh3zvHWHetdVxY5Eh'),
            ('mabel', 'Mabel', hp_ttgo,         'lNVVCXULoFj2wO61RvfaBq6ZzYDz7JtMOAkcwgoS9fv1yhR7'),
            ('hazel', 'Hazel', hp_ttgo,         'Hf0lIOl65il4D6HXooTGS9xBL0SdeXkvNoWQf8hyBnOPRXhi'),
        ]
        created = 0
        for slug, name, hp, token in nodes:
            node, c = Node.objects.get_or_create(slug=slug, defaults={
                'nickname': name, 'hardware_profile': hp,
                'api_token': token, 'enabled': True,
            })
            if not c:
                node.api_token = token
                node.save(update_fields=['api_token'])
            if c:
                created += 1
        self.stdout.write(f'  Fleet: {created} new nodes, {len(nodes)} total')

    def _seed_tiles(self):
        from tiles.models import Tile, TileSet

        # 2-color square checkerboard
        ts, c = TileSet.objects.get_or_create(
            name='2-color checkerboard',
            defaults={'tile_type': 'square',
                      'palette': ['#58a6ff', '#f85149'],
                      'source': 'seed'})
        if c:
            colors = ['#58a6ff', '#f85149']
            for i in range(4):
                Tile.objects.create(tileset=ts, name=f'T{i+1}',
                    n_color=colors[(i>>1)&1], e_color=colors[i&1],
                    s_color=colors[(i>>1)&1], w_color=colors[i&1],
                    sort_order=i)
            self.stdout.write(f'  Tiles: created {ts.name}')

        # Complete hex set
        ts2, c = TileSet.objects.get_or_create(
            name='Complete Hex (2-color)',
            defaults={'tile_type': 'hex',
                      'palette': ['#58a6ff', '#f85149'],
                      'source': 'seed',
                      'description': 'All 64 hexagonal Wang tiles with 2 colors.'})
        if c:
            colors = ['#58a6ff', '#f85149']
            for bits in range(64):
                Tile.objects.create(tileset=ts2, name=f'H{bits+1}',
                    n_color=colors[(bits>>5)&1], ne_color=colors[(bits>>4)&1],
                    se_color=colors[(bits>>3)&1], s_color=colors[(bits>>2)&1],
                    sw_color=colors[(bits>>1)&1], nw_color=colors[bits&1],
                    sort_order=bits)
            self.stdout.write(f'  Tiles: created {ts2.name} (64 hex tiles)')

        if not c:
            self.stdout.write('  Tiles: seed tilesets already exist')

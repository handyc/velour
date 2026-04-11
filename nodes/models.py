"""Field node inventory — individual ESP / microcontroller devices in the lab.

This is the `nodes` app, distinct from `hosts` (which tracks remote velour
instances for health monitoring). A Node is a physical microcontroller
attached to an experiment: an ESP32-WROOM in an aquarium, an ESP8266 on a
solar-powered monitor, an ESP32-S3 with LoRa in a remote building. Nodes
get human nicknames ("Gary") that have no relationship to hostnames,
MAC addresses, or URL slugs.
"""

import secrets
import string

from django.db import models
from django.utils.text import slugify


def _generate_api_token():
    """48-char URL-safe token, identical shape to secret_key / health_token."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(48))


class HardwareProfile(models.Model):
    """Catalog of microcontroller board variants the lab owns.

    Each physical Node picks a HardwareProfile from a dropdown. Adding a
    new board family to the lab means creating one HardwareProfile row
    once; from then on, every unit of that model reuses it. Queries like
    "all LoRa-capable nodes" or "every ESP8266 still in service" become
    trivial joins.
    """

    MCU_CHOICES = [
        ('esp8266',   'ESP8266'),
        ('esp32',     'ESP32 (classic, WROOM/WROVER)'),
        ('esp32s2',   'ESP32-S2'),
        ('esp32s3',   'ESP32-S3'),
        ('esp32c3',   'ESP32-C3'),
        ('esp32c6',   'ESP32-C6'),
        ('esp32h2',   'ESP32-H2'),
        ('rp2040',    'Raspberry Pi Pico (RP2040)'),
        ('avr',       'AVR (Arduino classic)'),
        ('other',     'Other / unknown'),
    ]

    name = models.CharField(
        max_length=120, unique=True,
        help_text="Board name as you'd recognize it in a parts box, "
                  'e.g. "ESP32-WROOM-32", "Wemos D1 mini", "TTGO LoRa32 v1.6".',
    )
    mcu = models.CharField(max_length=16, choices=MCU_CHOICES, default='esp32')
    flash_mb = models.PositiveIntegerField(null=True, blank=True, help_text='Flash size in MB.')
    ram_kb = models.PositiveIntegerField(null=True, blank=True, help_text='SRAM in KB.')
    has_wifi = models.BooleanField(default=True)
    has_bluetooth = models.BooleanField(default=False)
    has_lora = models.BooleanField(default=False)
    has_psram = models.BooleanField(default=False)
    adc_bits = models.PositiveIntegerField(null=True, blank=True, help_text='ADC resolution in bits.')
    gpio_count = models.PositiveIntegerField(null=True, blank=True, help_text='Usable GPIO count.')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def short_capabilities(self):
        """One-line capability summary for fleet list cards."""
        bits = [self.get_mcu_display()]
        if self.flash_mb:
            bits.append(f'{self.flash_mb}MB')
        if self.has_lora:
            bits.append('LoRa')
        if self.has_bluetooth:
            bits.append('BT')
        if self.has_psram:
            bits.append('PSRAM')
        return ' · '.join(bits)


class Node(models.Model):
    """One physical microcontroller device in the field.

    Identity hierarchy:
      - nickname  : "Gary" — human label, not unique (you might have
                    two Garys in different labs and that's fine).
      - slug      : "gary" — unique, URL-safe, used in API routes and
                    as the stable machine ID. Auto-derived from nickname
                    on first save if blank.
      - mac_address : unique when set, nullable (you may add a node
                    before reading its MAC off the chip).
      - hostname  : optional, e.g. "gary.local" for mDNS.
      - last_ip   : whatever the node last reported from its heartbeat.

    Solar / intermittent nodes use `power_mode` so the fleet UI can
    distinguish expected dormancy from actual failure.
    """

    POWER_CHOICES = [
        ('always_on', 'Always on (wall power)'),
        ('solar',     'Solar (dormant without sun)'),
        ('battery',   'Battery (finite runtime)'),
        ('on_demand', 'On demand (manually powered)'),
        ('unknown',   'Unknown / not specified'),
    ]

    nickname = models.CharField(
        max_length=100,
        help_text='Human-friendly name, e.g. "Gary". Not required to be unique.',
    )
    slug = models.SlugField(
        max_length=120, unique=True, blank=True,
        help_text='URL-safe unique ID. Auto-derived from nickname if blank.',
    )
    mac_address = models.CharField(
        max_length=32, blank=True,
        help_text='Hardware MAC address, e.g. AA:BB:CC:DD:EE:FF. Leave blank until known.',
    )
    hostname = models.CharField(
        max_length=253, blank=True,
        help_text='Optional network hostname, e.g. "gary.local" for mDNS.',
    )
    last_ip = models.GenericIPAddressField(null=True, blank=True)

    hardware_profile = models.ForeignKey(
        HardwareProfile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='nodes',
    )
    experiment = models.ForeignKey(
        'experiments.Experiment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='nodes',
    )

    power_mode = models.CharField(
        max_length=16, choices=POWER_CHOICES, default='unknown',
    )
    firmware_version = models.CharField(max_length=64, blank=True)
    api_token = models.CharField(
        max_length=64, unique=True, blank=True,
        help_text='Auto-generated on save. Sent by the ESP as '
                  'Authorization: Bearer <token> when posting telemetry.',
    )

    enabled = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    commissioned_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['nickname', 'slug']
        constraints = [
            models.UniqueConstraint(
                fields=['mac_address'],
                condition=~models.Q(mac_address=''),
                name='nodes_unique_mac_when_set',
            ),
        ]

    def __str__(self):
        return f'{self.nickname} ({self.slug})'

    def save(self, *args, **kwargs):
        if not self.slug and self.nickname:
            base = slugify(self.nickname)[:100] or 'node'
            # Ensure uniqueness by suffixing if needed.
            candidate = base
            n = 2
            while Node.objects.filter(slug=candidate).exclude(pk=self.pk).exists():
                candidate = f'{base}-{n}'
                n += 1
            self.slug = candidate
        if not self.api_token:
            self.api_token = _generate_api_token()
        # Normalize MAC address to uppercase with colons if non-empty.
        if self.mac_address:
            self.mac_address = self.mac_address.upper().strip()
        super().save(*args, **kwargs)

    @property
    def is_dormant_expected(self):
        """True when this node is in a power mode where being offline is
        normal — solar at night, battery when depleted, on_demand when off.
        The fleet list uses this to pick between 'dormant' (gray) and
        'offline' (red) styling."""
        return self.power_mode in ('solar', 'battery', 'on_demand')


class SensorReading(models.Model):
    """One data point reported by a Node.

    Schema is intentionally loose for Phase 1: channel is a free-text
    string so any node can report any sensor without pre-declaring it,
    and velour is happy to receive whatever it sends. Phase 2 will add
    a SensorChannel model per Experiment that validates channel names
    and units — existing readings will migrate by matching channel
    name to SensorChannel.slug.

    raw_json holds any extra per-reading metadata the node wanted to
    include (e.g. a timestamp the node generated, a unit hint, a
    calibration flag) — anything that isn't the canonical channel+value
    pair survives there for later inspection.
    """

    node = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name='readings',
    )
    channel = models.CharField(max_length=100)
    value = models.FloatField()
    received_at = models.DateTimeField(auto_now_add=True)
    raw_json = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['node', 'channel', '-received_at']),
            models.Index(fields=['-received_at']),
        ]

    def __str__(self):
        return f'{self.node.slug}/{self.channel} = {self.value}'


def _firmware_upload_path(instance, filename):
    profile_slug = slugify(instance.hardware_profile.name) if instance.hardware_profile else 'unknown'
    return f'firmware/{profile_slug}/{instance.version}.bin'


class Firmware(models.Model):
    """A compiled firmware binary targeting a specific HardwareProfile.

    One `is_active=True` row per HardwareProfile at a time. The OTA
    check endpoint picks that row for a node of matching profile. To
    roll back, upload the previous bin as a new version (bumped) and
    mark it active — rollback history is just the row list, ordered
    by uploaded_at.
    """

    name = models.CharField(
        max_length=120,
        help_text='Human label, e.g. "gary-aht20-sensor" or "greenhouse-monitor".',
    )
    hardware_profile = models.ForeignKey(
        HardwareProfile, on_delete=models.CASCADE, related_name='firmwares',
        help_text='Any Node with this hardware profile is eligible to pull this firmware.',
    )
    version = models.CharField(
        max_length=32,
        help_text='Version string the sketch reports via firmware_version, e.g. "0.1.2". '
                  'Compared byte-for-byte against what the node currently runs.',
    )
    bin_file = models.FileField(upload_to=_firmware_upload_path)
    sha256 = models.CharField(max_length=64, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(
        default=False,
        help_text='Exactly one row per HardwareProfile should be active. '
                  'Enabling a new row clears the flag on siblings in save().',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['hardware_profile', 'version'],
                name='nodes_firmware_unique_profile_version',
            ),
        ]

    def __str__(self):
        active = ' [active]' if self.is_active else ''
        return f'{self.name} {self.version} ({self.hardware_profile}){active}'

    def save(self, *args, **kwargs):
        if self.is_active and self.hardware_profile_id:
            Firmware.objects.filter(
                hardware_profile=self.hardware_profile, is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

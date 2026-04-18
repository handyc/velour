"""Bodymap — wearable biometric mesh.

Tracks which body-segment role each wearable Node has been assigned
(forearm_left, torso, upper_leg_r, etc.) plus optional per-pair link
observations for debugging the clustering layer's view of the mesh.

Role assignment is produced by the firmware's MotionCluster step once
pairwise coherence stabilises; it POSTs the result here so it survives
reboots and is visible to the dashboard. Operators can override a
firmware assignment via the Segment admin — the override sets
`operator_locked=True` and the server silently ignores further
autogen updates for that node until cleared.

Also hosts the ATtiny workshop (AttinyTemplate / AttinyDesign). Each
ATtiny85 is a custom analog-to-digital filter the user hangs off the
ESP32-S3's I2C bus; the workshop lets them edit C source in-browser,
compile via avr-gcc, and (phase 2) flash via USBasp.
"""

from django.db import models

from nodes.models import Node
from experiments.models import Experiment


class Segment(models.Model):
    ROLE_CHOICES = [
        ('torso',       'Torso'),
        ('head',        'Head'),
        ('neck',        'Neck'),
        ('upper_arm_l', 'Upper arm (left)'),
        ('upper_arm_r', 'Upper arm (right)'),
        ('forearm_l',   'Forearm (left)'),
        ('forearm_r',   'Forearm (right)'),
        ('upper_leg_l', 'Upper leg (left)'),
        ('upper_leg_r', 'Upper leg (right)'),
        ('lower_leg_l', 'Lower leg (left)'),
        ('lower_leg_r', 'Lower leg (right)'),
        ('unassigned', 'Unassigned'),
    ]

    node = models.OneToOneField(
        Node, on_delete=models.CASCADE, related_name='bodymap_segment',
    )
    experiment = models.ForeignKey(
        Experiment, on_delete=models.CASCADE,
        related_name='bodymap_segments',
        null=True, blank=True,
    )
    role = models.CharField(
        max_length=16, choices=ROLE_CHOICES, default='unassigned',
    )
    confidence = models.FloatField(default=0.0)
    operator_locked = models.BooleanField(
        default=False,
        help_text='If True, the firmware\'s role reports are ignored. '
                  'Set by an operator when clustering gets it wrong; '
                  'clear to let the firmware re-assign.',
    )
    assigned_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['role', 'node__slug']

    def __str__(self):
        return f'{self.node.slug} → {self.get_role_display()}'


class LinkObservation(models.Model):
    """One row per (reporter, peer_mac) per report cycle.

    N² growth per fleet per reporting cycle — potentially high volume.
    Safe to leave empty and rely on the firmware's live view; populate
    only when debugging the clustering layer.
    """

    reporter = models.ForeignKey(
        Node, on_delete=models.CASCADE, related_name='link_observations',
    )
    peer_mac = models.CharField(max_length=17)
    strength = models.FloatField()
    observed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-observed_at']
        indexes = [
            models.Index(fields=['reporter', 'observed_at']),
        ]

    def __str__(self):
        return f'{self.reporter.slug} ↔ {self.peer_mac}: {self.strength:.2f}'


MCU_CHOICES = [
    ('attiny85', 'ATtiny85'),
    ('attiny13a','ATtiny13a'),
]


class AttinyTemplate(models.Model):
    """Read-only starter firmware for an ATtiny coprocessor.

    Seed via `manage.py seed_attinys`. Each template is a complete,
    compilable C program against avr-libc for the chosen MCU. Users
    don't edit templates directly — they clone one into an
    AttinyDesign, then edit there.
    """

    slug        = models.SlugField(primary_key=True, max_length=80)
    name        = models.CharField(max_length=80)
    summary     = models.CharField(max_length=240, blank=True)
    description = models.TextField(
        blank=True,
        help_text='Longer explanation shown on the template card and in '
                  'the editor. Markdown-lite (paragraphs, not headings).',
    )
    mcu         = models.CharField(max_length=12, choices=MCU_CHOICES, default='attiny85')
    c_source    = models.TextField()
    pinout      = models.TextField(
        blank=True,
        help_text='Free-text pin notes, e.g. "PB2 = pot, PB0 = PWM out".',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class AttinyDesign(models.Model):
    """User-editable ATtiny program. Clone of a template, plus edits.

    i2c_address is the slave address the design will answer on once
    flashed — defaults to 0x08 and increments per design so a fresh
    workshop naturally assigns non-colliding addresses. Users can
    override if they want to slot a design into an existing mesh.
    """

    slug        = models.SlugField(unique=True, max_length=80)
    name        = models.CharField(max_length=80)
    template    = models.ForeignKey(
        AttinyTemplate,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='designs',
    )
    mcu         = models.CharField(max_length=12, choices=MCU_CHOICES, default='attiny85')
    c_source    = models.TextField()
    description = models.TextField(blank=True)

    i2c_address = models.PositiveSmallIntegerField(
        default=8,
        help_text='7-bit I2C slave address (0x08–0x77). ESP reads this '
                  'slot in the per-tick round-robin.',
    )

    # Compile artifacts — updated in place by the build view. Kept
    # inline rather than on disk so the editor page can render the
    # log alongside the source without chasing filesystem state.
    compiled_hex  = models.TextField(blank=True)
    compile_log   = models.TextField(blank=True)
    compiled_at   = models.DateTimeField(null=True, blank=True)
    compile_ok    = models.BooleanField(default=False)
    # .text size in bytes, pulled from avr-size -A. Helps the user see
    # at a glance whether they're running out of 8KB (ATtiny85) /
    # 1KB (ATtiny13a) flash.
    program_bytes = models.PositiveIntegerField(null=True, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f'{self.name} ({self.mcu})'

    @property
    def flash_limit_bytes(self):
        return 8192 if self.mcu == 'attiny85' else 1024

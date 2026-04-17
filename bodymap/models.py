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

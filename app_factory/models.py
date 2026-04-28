from django.db import models


class GeneratedApp(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('deployed', 'Deployed'),
        ('rejected', 'Rejected'),
    ]

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    directory = models.CharField(max_length=500)
    app_type = models.CharField(
        max_length=50,
        choices=[
            ('blank', 'Blank Django App'),
            ('clone', 'Clone of Velour'),
        ],
        default='blank',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True,
    )
    deploy_user = models.CharField(
        max_length=100, blank=True,
        help_text='Linux user to deploy under (created on approval)',
    )
    dev_port = models.IntegerField(
        null=True, blank=True,
        help_text='Port for local dev server (assigned on deploy)',
    )
    dev_pid = models.IntegerField(
        null=True, blank=True,
        help_text='PID of the local dev server process',
    )

    # --- customization baked into deploy artifacts + clone Identity --------
    # These are captured at create time and flow into:
    #   1. The deploy templates (nginx server_name, maintenance fallback).
    #   2. For clones: a clone_init.json at the cloned tree root, picked up
    #      by `manage.py apply_clone_init` so the new install's Identity
    #      singleton starts with the operator-chosen values rather than
    #      the originating instance's.
    server_name = models.CharField(
        max_length=253, blank=True,
        help_text='nginx server_name. Blank = derive as '
                  '<deploy_user>.<hostname-from-Identity>.',
    )
    hostname = models.CharField(
        max_length=253, blank=True,
        help_text='Base domain baked into the new clone\'s Identity row. '
                  'Blank = inherit from the originating install.',
    )
    admin_email = models.EmailField(
        blank=True,
        help_text='Default recipient for system mail in the new clone.',
    )
    maintenance_root = models.CharField(
        max_length=255, blank=True,
        help_text='Host directory nginx serves when the upstream socket '
                  'is down. Blank = /var/www/maintenance.',
    )
    instance_label = models.CharField(
        max_length=100, blank=True,
        help_text='What the new clone calls itself in its own UI. '
                  'Blank = the app name.',
    )
    # Comma-separated list of OPTIONAL_APPS slugs the operator selected.
    # Empty = all OPTIONAL apps included (full Velour clone). The clone
    # closure (resolved deps) is recomputed at clone time, not stored.
    selected_apps = models.TextField(
        blank=True,
        help_text='Comma-separated optional-app slugs. Empty = full clone.',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.status})'

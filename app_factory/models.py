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

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.status})'

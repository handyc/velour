from django.db import models


class Backup(models.Model):
    username = models.CharField(max_length=100)
    filename = models.CharField(max_length=300)
    filepath = models.CharField(max_length=500)
    size_bytes = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True,
    )
    notes = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.filename

    @property
    def size_display(self):
        if self.size_bytes > 1024 * 1024 * 1024:
            return f'{self.size_bytes / (1024**3):.1f} GB'
        if self.size_bytes > 1024 * 1024:
            return f'{self.size_bytes / (1024**2):.1f} MB'
        if self.size_bytes > 1024:
            return f'{self.size_bytes / 1024:.1f} KB'
        return f'{self.size_bytes} B'

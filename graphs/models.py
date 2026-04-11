import json

from django.db import models


class GraphSnapshot(models.Model):
    graph_type = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    data_json = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True,
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.title} ({self.created_at:%Y-%m-%d %H:%M})'

    @property
    def data(self):
        return json.loads(self.data_json)

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


class SystemSample(models.Model):
    """Ring-buffer row of live system metrics.

    Written every ~25 s — either as a side-effect of a /graphs/sample/
    poll (so any time the user is looking at graphs/sysinfo, samples
    accumulate) or by `manage.py sample_system` if you want fully
    unattended sampling on a cron. Pruned to a 48 h window on every
    insert; the table never grows unbounded.

    cpu_pct is computed at write time from a quick 80 ms double read of
    /proc/stat (so each row is internally consistent regardless of the
    gap to the previous row). mem and swap are stored as MB; the
    derived percentages live on the JSON history endpoint.
    """

    ts            = models.DateTimeField(auto_now_add=True, db_index=True)
    cpu_pct       = models.FloatField(default=0)
    mem_used_mb   = models.IntegerField(default=0)
    mem_total_mb  = models.IntegerField(default=0)
    mem_used_pct  = models.FloatField(default=0)
    swap_used_mb  = models.IntegerField(default=0)
    swap_total_mb = models.IntegerField(default=0)
    load1         = models.FloatField(default=0)
    load5         = models.FloatField(default=0)
    load15        = models.FloatField(default=0)
    entropy       = models.IntegerField(default=0)

    class Meta:
        ordering = ['-ts']

    def __str__(self):
        return f'sample {self.ts:%Y-%m-%d %H:%M:%S} cpu={self.cpu_pct:.1f}%'

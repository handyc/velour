from django.contrib import admin
from .models import Sequence, Run


@admin.register(Sequence)
class SequenceAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'shape', 'grid_w', 'grid_h',
                     'n_frames', 'source_app', 'created_at')
    list_filter = ('shape', 'source_app')
    search_fields = ('slug', 'name', 'notes')


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ('sequence', 'metric_name', 'fitness', 'created_at')
    list_filter = ('metric_name',)

from django.contrib import admin
from .models import Distillation


@admin.register(Distillation)
class DistillationAdmin(admin.ModelAdmin):
    list_display = ('name', 'source_tier', 'target_tier', 'status',
                    'output_size_bytes', 'created_at')
    list_filter = ('status', 'target_tier')

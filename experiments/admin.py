from django.contrib import admin

from .models import Experiment


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'is_intermittent', 'created_at')
    list_filter = ('status', 'is_intermittent')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

from django.contrib import admin

from .models import Walk


@admin.register(Walk)
class WalkAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'method', 'n_steps',
                    'fitness_final', 'created_at')
    list_filter = ('method', 'population_id')
    search_fields = ('slug', 'name', 'notes')

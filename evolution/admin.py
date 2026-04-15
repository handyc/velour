from django.contrib import admin

from .models import Agent, EvolutionRun


@admin.register(EvolutionRun)
class EvolutionRunAdmin(admin.ModelAdmin):
    list_display = ('name', 'level', 'status', 'generation',
                    'best_score', 'population_size', 'modified')
    list_filter = ('level', 'status')
    search_fields = ('name', 'slug', 'notes')
    readonly_fields = ('created', 'modified')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('name', 'level', 'score', 'parent',
                    'source_run', 'created')
    list_filter = ('level',)
    search_fields = ('name', 'slug', 'notes')
    readonly_fields = ('created',)
    prepopulated_fields = {'slug': ('name',)}
    raw_id_fields = ('parent', 'source_run')

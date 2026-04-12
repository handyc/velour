from django.contrib import admin

from .models import (
    IntrospectiveLayer, LoopTraversal, StrangeLoop, ThoughtExperiment,
)


@admin.register(StrangeLoop)
class StrangeLoopAdmin(admin.ModelAdmin):
    list_display = ('name', 'kind', 'discovered_by', 'is_active')
    list_filter = ('kind', 'discovered_by', 'is_active')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(LoopTraversal)
class LoopTraversalAdmin(admin.ModelAdmin):
    list_display = ('loop', 'started_at', 'steps_taken', 'exit_reason')
    list_filter = ('loop', 'exit_reason')
    readonly_fields = ('started_at', 'completed_at', 'steps')


@admin.register(ThoughtExperiment)
class ThoughtExperimentAdmin(admin.ModelAdmin):
    list_display = ('name', 'seed_layer', 'status', 'exit_reason',
                    'created_at')
    list_filter = ('status', 'seed_layer', 'exit_reason')
    search_fields = ('name', 'premise', 'conclusion')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('started_at', 'completed_at', 'trace', 'exit_reason',
                       'conclusion', 'status')


@admin.register(IntrospectiveLayer)
class IntrospectiveLayerAdmin(admin.ModelAdmin):
    list_display = ('layer', 'title', 'source', 'strength', 'is_active')
    list_filter = ('layer', 'source', 'is_active')
    search_fields = ('title', 'body')

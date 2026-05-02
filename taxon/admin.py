from django.contrib import admin

from .models import Classification, EvolutionRun, MetricRun, Rule


@admin.register(Rule)
class RuleAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'source', 'sha1', 'created_at')
    list_filter = ('source', 'kind', 'n_colors')
    search_fields = ('slug', 'name', 'sha1', 'source_ref')
    readonly_fields = ('sha1', 'created_at')


@admin.register(MetricRun)
class MetricRunAdmin(admin.ModelAdmin):
    list_display = ('rule', 'metric', 'value', 'computed_at')
    list_filter = ('metric',)
    search_fields = ('rule__slug', 'metric')


@admin.register(Classification)
class ClassificationAdmin(admin.ModelAdmin):
    list_display = ('rule', 'wolfram_class', 'confidence', 'assigned_at')
    list_filter = ('wolfram_class',)


@admin.register(EvolutionRun)
class EvolutionRunAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'target_kind', 'target_class',
                    'best_fitness', 'started_at')
    list_filter = ('target_kind', 'target_class')

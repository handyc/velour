from django.contrib import admin
from .models import StackGenome, EvolutionRun


@admin.register(StackGenome)
class StackGenomeAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'n_boards', 'board_side', 'fitness',
                       'test_set_id', 'created_at')
    list_filter   = ('test_set_id', 'n_boards')
    search_fields = ('slug', 'notes')


@admin.register(EvolutionRun)
class EvolutionRunAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'started_at', 'finished_at',
                       'n_generations', 'n_evals', 'best_genome')
    search_fields = ('slug', 'notes')

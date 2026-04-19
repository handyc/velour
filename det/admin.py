from django.contrib import admin

from .models import Candidate, SearchRun


@admin.register(SearchRun)
class SearchRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'label', 'n_colors', 'n_candidates',
                    'status', 'created_at', 'duration_seconds')
    list_filter = ('status', 'n_colors')
    readonly_fields = ('created_at', 'started_at', 'finished_at')


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'est_class', 'score', 'n_rules',
                    'promoted_to', 'created_at')
    list_filter = ('est_class', 'run')
    readonly_fields = ('created_at', 'rules_hash')

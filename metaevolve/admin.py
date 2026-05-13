from django.contrib import admin

from .models import Target, ArchivedWinner


@admin.register(Target)
class TargetAdmin(admin.ModelAdmin):
    list_display  = ('name', 'archetype', 'target_game', 'active',
                     'priority', 'total_runs', 'last_run_at')
    list_filter   = ('archetype', 'active')
    search_fields = ('name', 'archetype', 'notes')
    ordering      = ('-priority', 'name')


@admin.register(ArchivedWinner)
class ArchivedWinnerAdmin(admin.ModelAdmin):
    list_display  = ('target', 'fitness', 'created_at', 'materialised_session_slug')
    list_filter   = ('target', 'created_at')
    ordering      = ('-fitness', '-created_at')
    readonly_fields = ('gene_json', 'components_json', 'created_at')

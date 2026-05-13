from django.contrib import admin

from .models import GameSession


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ('name', 'pact', 'component', 'monster_count',
                    'wall_threshold', 'created_at')
    search_fields = ('name', 'pact__name')
    list_filter = ('wall_threshold',)

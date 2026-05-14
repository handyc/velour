from django.contrib import admin

from .models import Composition


@admin.register(Composition)
class CompositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_slug', 'motif_kind',
                    'tile_mm', 'updated_at')
    list_filter = ('group_slug', 'motif_kind')
    search_fields = ('name', 'slug')

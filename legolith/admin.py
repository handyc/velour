from django.contrib import admin

from .models import LegoWorld


@admin.register(LegoWorld)
class LegoWorldAdmin(admin.ModelAdmin):
    list_display = ('name', 'biome', 'seed',
                    'n_buildings', 'n_trees', 'n_flowers', 'n_people',
                    'n_decor', 'created_at')
    list_filter = ('biome',)
    search_fields = ('name', 'slug')
    readonly_fields = ('slug', 'created_at')

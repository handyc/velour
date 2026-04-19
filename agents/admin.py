from django.contrib import admin

from .models import Agent, AgentRelation, Town, TownCell


@admin.register(Town)
class TownAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'name', 'founded_year', 'population_target', 'created_at')
    search_fields = ('slug', 'name')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(TownCell)
class TownCellAdmin(admin.ModelAdmin):
    list_display  = ('town', 'q', 'r', 'label', 'world')
    list_filter   = ('town',)
    search_fields = ('label', 'world__title', 'town__slug')
    autocomplete_fields = ('town', 'world')


@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'name', 'family_name', 'gender',
                     'town', 'origin_world', 'bio_bytes')
    list_filter   = ('town', 'gender', 'origin_world')
    search_fields = ('slug', 'name', 'family_name')
    autocomplete_fields = ('town', 'origin_world', 'current_cell')
    readonly_fields = ('created_at', 'updated_at')

    def bio_bytes(self, obj):
        return obj.bio_size_bytes()
    bio_bytes.short_description = 'bio (B)'


@admin.register(AgentRelation)
class AgentRelationAdmin(admin.ModelAdmin):
    list_display  = ('src', 'kind', 'dst', 'since')
    list_filter   = ('kind',)
    search_fields = ('src__name', 'dst__name', 'src__family_name', 'dst__family_name')
    autocomplete_fields = ('src', 'dst')

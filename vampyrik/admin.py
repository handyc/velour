from django.contrib import admin

from .models import Creature, Origin, Source, Tradition, Trait, Weakness


@admin.register(Tradition)
class TraditionAdmin(admin.ModelAdmin):
    list_display  = ('name', 'region', 'era')
    search_fields = ('name', 'region', 'summary')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Creature)
class CreatureAdmin(admin.ModelAdmin):
    list_display  = ('name', 'tradition', 'updated_at')
    list_filter   = ('tradition',)
    search_fields = ('name', 'alt_names', 'summary', 'appearance', 'behaviour')
    autocomplete_fields = ('tradition',)
    filter_horizontal = ('traits', 'origins', 'weaknesses', 'sources')


@admin.register(Trait)
class TraitAdmin(admin.ModelAdmin):
    list_display  = ('name', 'kind')
    list_filter   = ('kind',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Origin)
class OriginAdmin(admin.ModelAdmin):
    list_display  = ('name',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Weakness)
class WeaknessAdmin(admin.ModelAdmin):
    list_display  = ('name', 'destroys')
    list_filter   = ('destroys',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display  = ('title', 'author', 'year')
    search_fields = ('title', 'author', 'details')

from django.contrib import admin

from .models import (
    SettingsScope, BundlePatchWish,
    Harness, Technique, Observation, DistillationProposal,
)


@admin.register(SettingsScope)
class SettingsScopeAdmin(admin.ModelAdmin):
    list_display = ('name', 'path', 'is_active', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('path',)


@admin.register(BundlePatchWish)
class BundlePatchWishAdmin(admin.ModelAdmin):
    list_display = ('kind', 'target', 'replacement', 'applied', 'created_at')
    list_filter = ('kind', 'applied')
    search_fields = ('target', 'replacement', 'notes')


@admin.register(Harness)
class HarnessAdmin(admin.ModelAdmin):
    list_display = ('name', 'vendor', 'surface', 'is_open_source',
                    'version_seen', 'updated_at')
    list_filter = ('surface', 'is_open_source', 'vendor')
    search_fields = ('name', 'slug', 'vendor', 'summary')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Technique)
class TechniqueAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'magic_weight',
                    'deterministic_cost', 'updated_at')
    list_filter = ('category', 'deterministic_cost')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('-magic_weight',)


@admin.register(Observation)
class ObservationAdmin(admin.ModelAdmin):
    list_display = ('harness', 'technique', 'source_kind',
                    'confidence', 'observed_at')
    list_filter = ('source_kind', 'harness', 'technique__category')
    search_fields = ('summary', 'evidence')
    autocomplete_fields = ('harness', 'technique')


@admin.register(DistillationProposal)
class DistillationProposalAdmin(admin.ModelAdmin):
    list_display = ('technique', 'decision', 'priority',
                    'byte_budget', 'updated_at')
    list_filter = ('decision', 'priority')
    search_fields = ('technique__name', 'rationale')
    autocomplete_fields = ('technique',)
    ordering = ('priority', '-technique__magic_weight')

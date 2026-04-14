from django.contrib import admin

from .models import (
    Asset, Entity, EntityScript, LibraryObject, ObjectCategory,
    Portal, SavedFace, Script, World, WorldPreset,
)


class AssetInline(admin.TabularInline):
    model = Asset
    extra = 0
    fields = ('name', 'slug', 'asset_type', 'file')


class EntityInline(admin.TabularInline):
    model = Entity
    extra = 0
    fields = ('name', 'primitive', 'pos_x', 'pos_y', 'pos_z',
              'behavior', 'visible', 'sort_order')


class PortalInline(admin.TabularInline):
    model = Portal
    fk_name = 'from_world'
    extra = 0
    fields = ('to_world', 'label', 'pos_x', 'pos_y', 'pos_z')


class EntityScriptInline(admin.TabularInline):
    model = EntityScript
    extra = 0
    fields = ('script', 'props', 'enabled', 'sort_order')


@admin.register(World)
class WorldAdmin(admin.ModelAdmin):
    list_display = ('title', 'skybox', 'published', 'featured', 'updated_at')
    list_filter = ('published', 'featured', 'skybox')
    search_fields = ('title', 'description')
    inlines = [AssetInline, EntityInline, PortalInline]


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ('name', 'world', 'asset_type', 'created_at')
    list_filter = ('asset_type', 'world')
    search_fields = ('name',)


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ('name', 'world', 'primitive', 'behavior', 'visible')
    list_filter = ('behavior', 'world')
    search_fields = ('name',)
    inlines = [EntityScriptInline]


@admin.register(Portal)
class PortalAdmin(admin.ModelAdmin):
    list_display = ('from_world', 'to_world', 'label')
    list_filter = ('from_world',)


@admin.register(Script)
class ScriptAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'is_builtin', 'updated_at')
    list_filter = ('event', 'is_builtin')
    search_fields = ('name', 'description')


@admin.register(ObjectCategory)
class ObjectCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent')
    list_filter = ('parent',)
    search_fields = ('name',)


@admin.register(LibraryObject)
class LibraryObjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'source', 'license', 'downloaded',
                    'use_count')
    list_filter = ('source', 'license', 'downloaded', 'category')
    search_fields = ('name', 'tags', 'description')


@admin.register(WorldPreset)
class WorldPresetAdmin(admin.ModelAdmin):
    list_display = ('name', 'skybox', 'hdri_asset', 'ambient_audio_url')
    search_fields = ('name',)


@admin.register(SavedFace)
class SavedFaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'lineage', 'use_count', 'favorite', 'created_at')
    list_filter = ('favorite',)
    search_fields = ('name',)

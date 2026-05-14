from django.contrib import admin

from .models import SettingsScope, BundlePatchWish


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

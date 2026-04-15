from django.contrib import admin

from .models import Language


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'seed', 'created', 'modified')
    search_fields = ('name', 'slug', 'notes')
    readonly_fields = ('created', 'modified')
    prepopulated_fields = {'slug': ('name',)}

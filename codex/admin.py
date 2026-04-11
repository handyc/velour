from django.contrib import admin

from .models import Manual, Section


class SectionInline(admin.TabularInline):
    model = Section
    fields = ('sort_order', 'title', 'slug')
    extra = 0
    ordering = ('sort_order',)


@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ('title', 'format', 'version', 'updated_at', 'last_built_at')
    list_filter = ('format',)
    search_fields = ('title', 'subtitle', 'abstract')
    inlines = [SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('manual', 'sort_order', 'title')
    list_filter = ('manual',)
    list_editable = ('sort_order',)
    search_fields = ('title', 'body')

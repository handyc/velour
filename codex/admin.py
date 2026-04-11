from django.contrib import admin

from .models import Figure, Manual, Section


class SectionInline(admin.TabularInline):
    model = Section
    fields = ('sort_order', 'title', 'slug')
    extra = 0
    ordering = ('sort_order',)


class FigureInline(admin.TabularInline):
    model = Figure
    fields = ('sort_order', 'slug', 'kind', 'caption')
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
    inlines = [FigureInline]


@admin.register(Figure)
class FigureAdmin(admin.ModelAdmin):
    list_display = ('section', 'slug', 'kind', 'sort_order')
    list_filter = ('kind', 'section__manual')
    search_fields = ('slug', 'caption', 'source')

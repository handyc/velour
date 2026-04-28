from django.contrib import admin

from .models import Cell, FormulaLanguage, NamedRange, Sheet, Workbook


@admin.register(FormulaLanguage)
class FormulaLanguageAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'version')


class SheetInline(admin.TabularInline):
    model = Sheet
    extra = 0


@admin.register(Workbook)
class WorkbookAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'owner', 'formula_language', 'updated_at')
    search_fields = ('title', 'slug')
    readonly_fields = ('slug', 'created_at', 'updated_at')
    inlines = [SheetInline]


@admin.register(Sheet)
class SheetAdmin(admin.ModelAdmin):
    list_display = ('workbook', 'name', 'rows', 'cols')


@admin.register(Cell)
class CellAdmin(admin.ModelAdmin):
    list_display = ('sheet', 'row', 'col', 'value', 'computed_value')
    list_filter = ('sheet',)


@admin.register(NamedRange)
class NamedRangeAdmin(admin.ModelAdmin):
    list_display = ('workbook', 'name', 'a1_range')

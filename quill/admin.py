from django.contrib import admin

from .models import (
    CrossReference,
    Document,
    DocumentLanguage,
    Footnote,
    Language,
    Section,
    Style,
)


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'native_name', 'bcp47', 'direction',
                    'script_name', 'slug')
    list_filter = ('direction', 'script_name')
    search_fields = ('name', 'native_name', 'slug', 'bcp47', 'script_name')


@admin.register(DocumentLanguage)
class DocumentLanguageAdmin(admin.ModelAdmin):
    list_display = ('document', 'language', 'order')
    list_filter = ('language',)


class StyleInline(admin.TabularInline):
    model = Style
    extra = 0


class SectionInline(admin.TabularInline):
    model = Section
    extra = 0
    fields = ('order', 'level', 'title', 'parent', 'style')
    show_change_link = True


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'owner', 'updated_at', 'section_count')
    search_fields = ('title', 'slug')
    readonly_fields = ('created_at', 'updated_at', 'slug')
    inlines = [StyleInline, SectionInline]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ('document', 'order', 'level', 'title', 'style')
    list_filter = ('document', 'level')
    search_fields = ('title', 'body')


@admin.register(Style)
class StyleAdmin(admin.ModelAdmin):
    list_display = ('document', 'name', 'kind')
    list_filter = ('kind',)


@admin.register(Footnote)
class FootnoteAdmin(admin.ModelAdmin):
    list_display = ('section', 'order')


@admin.register(CrossReference)
class CrossReferenceAdmin(admin.ModelAdmin):
    list_display = ('source', 'target', 'label')

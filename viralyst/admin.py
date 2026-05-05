from django.contrib import admin

from .models import Corpus, Language, Sample


@admin.register(Corpus)
class CorpusAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_quarantined', 'license_summary')
    list_filter = ('is_quarantined',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    list_display = ('name', 'family', 'tier')
    list_filter = ('family', 'tier')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Sample)
class SampleAdmin(admin.ModelAdmin):
    list_display = ('name', 'language', 'kind', 'year', 'corpus',
                    'binary_size_bytes', 'is_quarantined')
    list_filter = ('kind', 'language__family', 'corpus', 'is_quarantined')
    search_fields = ('name', 'slug', 'author', 'notes_md')
    prepopulated_fields = {'slug': ('name',)}
    autocomplete_fields = ('corpus', 'language')
    readonly_fields = ('created_at', 'updated_at')

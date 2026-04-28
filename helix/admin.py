from django.contrib import admin

from .models import AnnotationFeature, SequenceRecord


class AnnotationFeatureInline(admin.TabularInline):
    model = AnnotationFeature
    extra = 0
    fields = ('feature_type', 'start', 'end', 'strand', 'qualifiers')


@admin.register(SequenceRecord)
class SequenceRecordAdmin(admin.ModelAdmin):
    list_display = ('title', 'accession', 'organism', 'sequence_type',
                    'length_bp', 'source_format', 'created_at')
    list_filter = ('sequence_type', 'source_format')
    search_fields = ('title', 'accession', 'organism')
    readonly_fields = ('length_bp', 'created_at')
    inlines = [AnnotationFeatureInline]


@admin.register(AnnotationFeature)
class AnnotationFeatureAdmin(admin.ModelAdmin):
    list_display = ('record', 'feature_type', 'start', 'end', 'strand')
    list_filter = ('feature_type', 'strand')
    search_fields = ('record__title', 'feature_type')

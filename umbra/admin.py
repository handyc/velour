from django.contrib import admin

from .models import Scheme, Reference, Experiment


@admin.register(Scheme)
class SchemeAdmin(admin.ModelAdmin):
    list_display  = ('name', 'family', 'datatype', 'bootstrappable',
                     'year_introduced')
    list_filter   = ('datatype', 'bootstrappable', 'family')
    search_fields = ('name', 'family', 'paper_title', 'summary')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display  = ('title', 'kind', 'authors', 'year')
    list_filter   = ('kind', 'year')
    search_fields = ('title', 'authors', 'summary', 'tags')
    filter_horizontal = ('schemes',)
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display  = ('name', 'scheme', 'status', 'last_run_ms', 'updated_at')
    list_filter   = ('status', 'scheme')
    search_fields = ('name', 'description', 'code')
    prepopulated_fields = {'slug': ('name',)}

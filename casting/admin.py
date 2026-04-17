from django.contrib import admin

from .models import Experiment


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = (
        'display_order', 'status', 'title', 'weight_bits',
        'search_method', 'c_source_filename', 'js_module_name',
    )
    list_display_links = ('title',)
    list_editable = ('display_order', 'status')
    list_filter = ('status',)
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('display_order',)

from django.contrib import admin

from .models import AttinyDesign, AttinyTemplate, LinkObservation, Segment


@admin.register(Segment)
class SegmentAdmin(admin.ModelAdmin):
    list_display = ('node', 'role', 'confidence',
                    'operator_locked', 'experiment', 'assigned_at')
    list_filter = ('role', 'operator_locked', 'experiment')
    list_editable = ('role', 'operator_locked')
    search_fields = ('node__slug', 'node__nickname')
    readonly_fields = ('assigned_at',)
    autocomplete_fields = ('node', 'experiment')


@admin.register(LinkObservation)
class LinkObservationAdmin(admin.ModelAdmin):
    list_display = ('reporter', 'peer_mac', 'strength', 'observed_at')
    list_filter = ('reporter',)
    search_fields = ('reporter__slug', 'peer_mac')
    readonly_fields = ('observed_at',)


@admin.register(AttinyTemplate)
class AttinyTemplateAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'name', 'mcu', 'updated_at')
    list_filter   = ('mcu',)
    search_fields = ('slug', 'name', 'summary')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AttinyDesign)
class AttinyDesignAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'name', 'mcu', 'template', 'i2c_address',
                     'compile_ok', 'program_bytes', 'updated_at')
    list_filter   = ('mcu', 'compile_ok')
    search_fields = ('slug', 'name', 'description')
    autocomplete_fields = ('template',)
    readonly_fields = ('created_at', 'updated_at', 'compiled_at',
                       'compile_ok', 'compile_log', 'compiled_hex',
                       'program_bytes')

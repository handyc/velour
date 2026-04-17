from django.contrib import admin

from .models import LinkObservation, Segment


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

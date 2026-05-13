from django.contrib import admin

from .models import Pact


@admin.register(Pact)
class PactAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'party_a', 'party_b',
                    'clock_model', 'launch_time', 'created_at')
    list_filter = ('clock_model',)
    search_fields = ('name', 'party_a', 'party_b', 'notes')
    readonly_fields = ('created_at', 'seed_hex', 'rule_hex')
    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'party_a', 'party_b',
                       'clock_model', 'tick_ms', 'launch_time', 'notes'),
        }),
        ('Snapshot (sealed at creation)', {
            'fields': ('palette', 'seed_hex', 'rule_hex'),
        }),
        ('Bookkeeping', {
            'fields': ('created_at', 'created_by'),
        }),
    )

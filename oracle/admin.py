from django.contrib import admin

from .models import OracleLabel


@admin.register(OracleLabel)
class OracleLabelAdmin(admin.ModelAdmin):
    list_display = ('happened_at', 'lobe_name', 'predicted', 'verdict',
                    'actual', 'linked_model', 'linked_pk')
    list_filter = ('lobe_name', 'verdict', 'actual_source')
    date_hierarchy = 'happened_at'
    readonly_fields = ('happened_at', 'features', 'linked_model', 'linked_pk')
    search_fields = ('lobe_name', 'predicted', 'actual', 'notes')

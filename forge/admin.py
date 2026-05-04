from django.contrib import admin

from .models import Circuit


@admin.register(Circuit)
class CircuitAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'width', 'height',
                    'rule_name', 'updated_at')
    search_fields = ('name', 'slug', 'rule_name')
    readonly_fields = ('created_at', 'updated_at')

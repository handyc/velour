from django.contrib import admin

from .models import LocalDelivery, SMTPServerConfig


@admin.register(LocalDelivery)
class LocalDeliveryAdmin(admin.ModelAdmin):
    list_display = ('from_addr', 'subject', 'received_at', 'read')
    list_filter = ('read',)
    date_hierarchy = 'received_at'
    readonly_fields = ('received_at', 'peer_ip', 'raw')
    search_fields = ('from_addr', 'subject', 'body_text')


@admin.register(SMTPServerConfig)
class SMTPServerConfigAdmin(admin.ModelAdmin):
    list_display = ('host', 'port', 'is_enabled', 'updated_at')

from django.contrib import admin

from .models import InboundMessage, LocalDelivery, MailAccount, SMTPServerConfig


@admin.register(MailAccount)
class MailAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'smtp_host', 'smtp_port', 'is_default', 'enabled', 'last_test_status')
    list_filter = ('enabled', 'is_default', 'last_test_status')
    search_fields = ('name', 'smtp_host', 'from_email')
    fieldsets = (
        (None, {'fields': ('name', 'enabled', 'is_default', 'notes')}),
        ('Outgoing (SMTP)', {'fields': (
            'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'smtp_use_tls', 'smtp_use_ssl', 'from_email', 'from_name',
        )}),
        ('Incoming (IMAP)', {'fields': (
            'imap_host', 'imap_port', 'imap_username', 'imap_password', 'imap_use_ssl',
        ), 'classes': ('collapse',)}),
        ('Last Test', {'fields': ('last_tested_at', 'last_test_status', 'last_test_error'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('last_tested_at', 'last_test_status', 'last_test_error')


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ('fetched_at', 'mailbox', 'from_addr', 'subject', 'read', 'handled')
    list_filter = ('mailbox', 'read', 'handled')
    search_fields = ('from_addr', 'to_addr', 'subject', 'body_text')
    readonly_fields = ('mailbox', 'uid', 'fetched_at', 'raw')
    date_hierarchy = 'fetched_at'


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

from django.contrib import admin

from .models import MailAccount


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

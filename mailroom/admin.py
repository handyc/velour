from django.contrib import admin

from .models import InboundMessage


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ('fetched_at', 'mailbox', 'from_addr', 'subject', 'read', 'handled')
    list_filter = ('mailbox', 'read', 'handled')
    search_fields = ('from_addr', 'to_addr', 'subject', 'body_text')
    readonly_fields = ('mailbox', 'uid', 'fetched_at', 'raw')
    date_hierarchy = 'fetched_at'

from django.contrib import admin

from .models import Policy, IrcContact, BotSession, BotMessage, VibegamePush


@admin.register(Policy)
class PolicyAdmin(admin.ModelAdmin):
    list_display = ('target', 'slug', 'title', 'updated_at')
    list_filter = ('target',)
    search_fields = ('slug', 'title', 'body')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(IrcContact)
class IrcContactAdmin(admin.ModelAdmin):
    list_display = ('nick', 'display', 'role', 'timezone')
    search_fields = ('nick', 'display', 'role', 'notes')


class BotMessageInline(admin.TabularInline):
    model = BotMessage
    extra = 0
    readonly_fields = ('direction', 'sender', 'body', 'at')


@admin.register(BotSession)
class BotSessionAdmin(admin.ModelAdmin):
    list_display = ('nick', 'target', 'status', 'message_cap',
                    'autonomous', 'created_at')
    list_filter = ('status', 'autonomous')
    search_fields = ('nick', 'target', 'purpose')
    inlines = [BotMessageInline]


@admin.register(VibegamePush)
class VibegamePushAdmin(admin.ModelAdmin):
    list_display = ('project', 'filename', 'response_code',
                    'bytes_sent', 'pushed_at')
    list_filter = ('project',)
    search_fields = ('project', 'filename', 'source_path')

from django.contrib import admin

from .models import SlotPatch


@admin.register(SlotPatch)
class SlotPatchAdmin(admin.ModelAdmin):
    list_display = ('slug', 'name', 'slot', 'elf_bytes', 'push_count',
                    'success_count', 'last_pushed_to', 'created_at')
    list_filter = ('slot',)
    search_fields = ('slug', 'name', 'elf_sha1', 'last_pushed_to')
    readonly_fields = ('elf_sha1', 'created_at', 'last_push_at')

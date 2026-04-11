from django.contrib import admin

from .models import HardwareProfile, Node


@admin.register(HardwareProfile)
class HardwareProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'mcu', 'flash_mb', 'has_wifi', 'has_lora', 'has_bluetooth', 'has_psram')
    list_filter = ('mcu', 'has_wifi', 'has_lora', 'has_bluetooth', 'has_psram')
    search_fields = ('name', 'notes')


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('nickname', 'slug', 'hardware_profile', 'experiment', 'power_mode', 'enabled', 'last_seen_at')
    list_filter = ('enabled', 'power_mode', 'hardware_profile', 'experiment')
    search_fields = ('nickname', 'slug', 'mac_address', 'hostname', 'notes')
    readonly_fields = ('api_token', 'commissioned_at', 'last_seen_at')
    prepopulated_fields = {'slug': ('nickname',)}
